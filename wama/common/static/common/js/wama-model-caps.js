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
 *
 * Extensions déclaratives (2026-08-17, adoption ×3 — zéro cas d'app ici) :
 *   meta:     {cléRésolue: capsDict} — capacités injectées CÔTÉ SERVEUR (vue), fusionnées
 *             PAR-DESSUS celles du fetch (ex. anonymizer : couverture de classes calculée
 *             par la brique d'alias Python — l'appariement ne se réinvente pas en JS).
 *   controls: [{id|selector, disableWhen(caps, el), reason}] — DÉSACTIVE un contrôle
 *             non-<select> (checkbox…) avec la raison en title ; jamais caché (doctrine
 *             INPUT_MODEL_MATCHING : désactiver + expliquer). caps null → réactivé.
 *   sections: [{selector, showWhen(caps)}] — affiche/masque un BLOC de réglages selon les
 *             capacités (remplace les toggles hardcodés par moteur, ex. .resemble-only).
 *             caps null → état laissé tel quel (dégradation douce).
 */
(function (global) {
  'use strict';

  function init(cfg) {
    cfg = cfg || {};
    const sel = document.getElementById(cfg.modelSelectId);
    if (!sel) return null;
    const resolveKey = cfg.resolveKey || function (v) { return v; };
    const filters = cfg.filters || [];
    const controls = cfg.controls || [];
    const sections = cfg.sections || [];
    const base = cfg.url || '/model-manager/api/models/db/';
    let capsByKey = {};
    // Meta serveur : disponible AVANT le fetch (filtrage initial sans réseau) puis
    // fusionnée par-dessus les capacités du catalogue.
    const metaByKey = cfg.meta || {};
    Object.keys(metaByKey).forEach(function (k) {
      capsByKey[k] = Object.assign({}, capsByKey[k], metaByKey[k]);
    });

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

    function applyControl(c, caps) {
      const els = c.selector ? document.querySelectorAll(c.selector)
                             : [document.getElementById(c.id)].filter(Boolean);
      els.forEach(function (el) {
        const dis = !!caps && typeof c.disableWhen === 'function' && !!c.disableWhen(caps, el);
        el.disabled = dis;
        const host = el.closest('label, .form-check') || el;
        host.classList.toggle('opacity-50', dis);
        host.title = dis ? (c.reason || 'Non géré par ce modèle') : '';
      });
    }

    function applySection(s, caps) {
      if (!caps || typeof s.showWhen !== 'function') return;  // dégradation douce
      const show = !!s.showWhen(caps);
      document.querySelectorAll(s.selector).forEach(function (el) {
        el.style.display = show ? '' : 'none';
      });
    }

    function render() {
      const caps = capsByKey[resolveKey(sel.value)] || null;
      filters.forEach(function (f) { applyFilter(f, caps); });
      controls.forEach(function (c) { applyControl(c, caps); });
      sections.forEach(function (s) { applySection(s, caps); });
    }

    sel.addEventListener('change', render);
    render();  // 1er passage sur la meta serveur (sans attendre le réseau)

    // Charge les capacités du catalogue puis applique le filtrage initial.
    const url = base + '?source=' + encodeURIComponent(cfg.source);
    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        (data.models || []).forEach(function (m) {
          if (m.model_key) {
            capsByKey[m.model_key] = Object.assign(
              {}, m.capabilities || {}, metaByKey[m.model_key] || {});
          }
        });
        render();
      })
      .catch(function () { /* pas de catalogue → on ne filtre pas (dégradation douce) */ });

    return { render: render, caps: function () { return capsByKey; } };
  }

  global.WamaModelCaps = { init: init };
})(window);
