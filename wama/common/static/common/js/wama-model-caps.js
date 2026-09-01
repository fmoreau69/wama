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
 *     task: 'text-to-speech',       // domaine par CAPACITÉ (préféré) — ou source: '<app>'
 *     modelSelectId: 'tts_model',
 *     // resolveKey inutile quand les valeurs du select SONT les clés catalogue (cf. F4b ②)
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
 * capabilities proviennent de api/models/db/ (champ `capabilities`), interrogé par `task`
 * (domaine par CAPACITÉ, route F4b) ou à défaut par `source` (voie historique, par app).
 *
 * ⚠ `task` DOIT border le même domaine que les options du select. Quand le select est peuplé
 * par `options_source: 'catalog'` + `options_query: {task}`, interroger ici par `source`
 * laisse sans capacités tout modèle d'une autre source — et le filtrage voix/langues
 * s'ABSENTE alors en silence (`caps = null` → dégradation douce). *Deux requêtes qui ne
 * bornent pas le même domaine produisent un filtre qui a l'air de marcher.*
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
 *
 * 3ᵉ état d'une option (2026-08-29) : `annotateOption(caps, opt) -> raison|null` sur un filtre.
 *   `hideOption` ne connaît que « géré / pas géré ». Or une capacité peut être RENDUE par un
 *   chemin d'emprunt : Kokoro rabat 8 des 15 langues du select sur son pipeline anglais — il
 *   sort un fichier, avec une voix anglaise. La cacher ferait dire « impossible » là où un son
 *   sort ; la laisser nue ferait croire à un support natif. `annotateOption` la garde
 *   SÉLECTIONNABLE en marquant son libellé (⚠) et en portant la raison en `title`.
 *   Même doctrine qu'`INPUT_MODEL_MATCHING` : on informe, on ne cache pas.
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
        // Libellé d'origine mémorisé au 1er passage : `render()` rejoue à chaque changement de
        // modèle, et un marqueur réappliqué sur un libellé déjà marqué s'empilerait.
        if (opt.dataset.capsLabel === undefined) opt.dataset.capsLabel = opt.textContent;
        const raison = (!hide && !!caps && typeof f.annotateOption === 'function')
                       ? f.annotateOption(caps, opt) : null;
        opt.textContent = raison ? '⚠ ' + opt.dataset.capsLabel : opt.dataset.capsLabel;
        opt.title = raison || '';
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
    // Domaine : par TÂCHE (capacité) si déclarée, sinon par SOURCE (voie historique).
    const url = base + (cfg.task
      ? '?task=' + encodeURIComponent(cfg.task)
      : '?source=' + encodeURIComponent(cfg.source));
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

  /*
   * Filtre LANGUE prêt à l'emploi — la couverture linguistique d'un modèle est un fait
   * CANONIQUE (`capabilities.languages` + `capabilities.fallback_languages`, cf.
   * `common/utils/model_capabilities.py`), pas une règle d'app. Le prédicat vivait recopié
   * mot pour mot dans le synthesizer ET l'avatarizer ; deux copies d'un même prédicat sont
   * deux occasions de le corriger à moitié. Il est donc DÉFINI ICI, une fois.
   *
   *   filters: [ WamaModelCaps.langFilter('language') ]
   *
   * Trois états, dans cet ordre de lecture :
   *   • dans `languages`          → option normale ;
   *   • dans `fallback_languages` → option gardée, marquée ⚠ + raison en title ;
   *   • ni l'un ni l'autre        → masquée/désactivée.
   * `languages` vide ou absent ⇒ AUCUNE restriction affirmée (catalogue muet ≠ « rien n'est
   * supporté » : cette confusion fermerait le select entier sur une simple panne de fetch).
   */
  function langFilter(selectId, opts) {
    opts = opts || {};
    const raison = opts.reason
      || 'Le moteur ne parle pas cette langue nativement : il la prononcera avec une voix '
         + 'd\'une autre langue. Un fichier sera produit, mais l\'accent ne sera pas natif.';
    function connues(caps) {
      return Array.isArray(caps.languages) && caps.languages.length > 0
             && caps.languages.indexOf('*') === -1;
    }
    return {
      selectId: selectId,
      hideOption: function (caps, opt) {
        if (!connues(caps)) return false;
        if (caps.languages.indexOf(opt.value) !== -1) return false;
        return (caps.fallback_languages || []).indexOf(opt.value) === -1;
      },
      annotateOption: function (caps, opt) {
        if (!connues(caps) || caps.languages.indexOf(opt.value) !== -1) return null;
        return (caps.fallback_languages || []).indexOf(opt.value) !== -1 ? raison : null;
      },
    };
  }

  global.WamaModelCaps = { init: init, langFilter: langFilter };
})(window);
