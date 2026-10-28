/*
 * wama-model-caps.js — Filtrage dynamique des <select> dépendants selon les CAPACITÉS
 * du modèle sélectionné (source unique : AIModel.capabilities via api/models/db/).
 *
 * Cas d'usage : masquer les voix de clonage (« Mes voix », `ua_`) si le modèle TTS ne clone
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
 *         hideOption: (caps, opt) => caps.supports_cloning === false && WamaModelCaps.isClonedVoice(opt.value) },
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

    // `loaded` : le catalogue a répondu. Avant, « pas de capacités » veut dire « pas encore » —
    // rien ne se juge ; après, il veut dire « ce choix n'a pas de fiche » (« auto ») : une voix
    // propre à un moteur se cache alors (`hideWithoutCaps`), aucun moteur n'étant désigné.
    let loaded = false;

    function render() {
      const key = resolveKey(sel.value);
      const caps = capsByKey[key] || null;
      filters.forEach(function (f) {
        applyOptionFilter(document.getElementById(f.selectId), f, caps, key, loaded);
      });
      controls.forEach(function (c) { applyControl(c, caps); });
      sections.forEach(function (s) { applySection(s, caps); });
    }

    sel.addEventListener('change', render);
    // Les options d'un select FILTRÉ peuvent être REMPLACÉES après coup — la recharge asynchrone
    // de WamaParams (`options_source`) les réécrit, puis émet `wama:options-filled`. Sans ce
    // rejeu, l'état posé ici (voix clonées masquées, ⚠ de langue) était perdu dès que la recharge
    // arrivait APRÈS ce passage : l'ordre de deux requêtes décidait du résultat (2026-09-22).
    filters.forEach(function (f) {
      const target = document.getElementById(f.selectId);
      if (target) target.addEventListener('wama:options-filled', render);
    });
    render();  // 1er passage sur la meta serveur (sans attendre le réseau)

    // Charge les capacités du catalogue puis applique le filtrage initial.
    // Domaine : par TÂCHE (capacité) si déclarée, sinon par SOURCE (voie historique).
    const url = base + (cfg.task
      ? '?task=' + encodeURIComponent(cfg.task)
      : '?source=' + encodeURIComponent(cfg.source));
    // `ready` (2026-10-05) : se résout quand les capacités du catalogue sont là (ou que le fetch a
    // échoué). Un consommateur qui juge AVANT (l'appariement `WamaInputMatch`, `capsReady`) lisait
    // des capacités vides et ne rejugeait jamais : une langue choisie ne grisait les moteurs
    // qu'au geste suivant, et un slot de capacité (la voix « Chanson » du composer) aurait tout
    // grisé à l'ouverture.
    const ready = fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        (data.models || []).forEach(function (m) {
          if (m.model_key) {
            capsByKey[m.model_key] = Object.assign(
              {}, m.capabilities || {}, metaByKey[m.model_key] || {});
          }
        });
        loaded = true;
        render();
        return capsByKey;
      })
      .catch(function () { return capsByKey; /* pas de catalogue → on ne filtre pas */ });

    return { render: render, caps: function () { return capsByKey; }, ready: ready };
  }

  /*
   * Applique UN filtre d'options au <select> `target` pour le modèle `key` (capacités `caps`) —
   * la règle commune, partagée avec `WamaParams` (`cap_from` en mode `voices`, 2026-10-28). Une
   * option masquée est aussi désactivée ; la sélection passe à la 1re visible si la sienne l'est.
   * `loaded` faux et `caps` absentes : rien ne se juge (le catalogue n'a pas encore répondu).
   */
  function applyOptionFilter(target, f, caps, key, loaded) {
    if (!target || typeof f.hideOption !== 'function') return;
    let firstVisible = null;
    let selectedHidden = false;
    Array.prototype.forEach.call(target.options, function (opt) {
      const hide = caps ? !!f.hideOption(caps, opt, key)
        : (!!loaded && typeof f.hideWithoutCaps === 'function' && !!f.hideWithoutCaps(opt));
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

  /*
   * Une voix CLONÉE se reconnaît à son identifiant : `ua_<id>` (voix de la médiathèque d'un
   * utilisateur) — jumeau de `is_cloned_voice` (common/tts/voice_refs) côté serveur. Le préfixe
   * hérité `cv_` est RETIRÉ le 2026-09-30 (sa seule ligne convertie en `ua_`). Ce prédicat vivait RECOPIÉ sur QUATRE sites
   * dans DEUX apps (2 hideOption + 2 isProvided, synthesizer et avatarizer) : quatre occasions
   * de le corriger à moitié le jour où un 3ᵉ préfixe apparaît (mesuré le 2026-09-12). Il est
   * DÉFINI ICI, une fois ; les deux briques (celle-ci et wama-input-match) le LISENT.
   */
  function isClonedVoice(value) {
    return /^ua_/.test(String(value || ''));
  }

  /*
   * Filtre VOIX prêt à l'emploi — direction MODÈLE → voix : un moteur qui déclare ne pas
   * cloner (`supports_cloning === false` — un fait du CATALOGUE, réaligné sur la classe de
   * moteur à chaque synchro depuis le 2026-09-12) masque les voix clonées. `null`/absent ⇒
   * aucune restriction affirmée : même lecture que langFilter, un catalogue muet n'est pas
   * un moteur qui ne clone pas.
   *
   * Et la LANGUE de la voix (2026-09-13, marche 6) : une option qui porte `data-language`
   * (voix de référence de la médiathèque — `attributes.language` — ou voix de l'utilisateur
   * qui l'a renseignée) est marquée ⚠ quand le moteur ne parle cette langue ni nativement ni
   * en repli. AVERTISSEMENT, jamais masquage : un timbre se clone d'une langue à l'autre, la
   * prononciation seule n'est pas garantie — c'est ce que la raison dit. Sans `data-language`,
   * rien n'est affirmé.
   *
   * Et les voix PROPRES d'un moteur (2026-10-28, Phonon) : une option qui porte `data-model`
   * (`voice_options.engine_voice_groups`) ne se montre que sous CE modèle — sous un autre, et sous
   * « auto » (aucun moteur désigné), elle se cache : un moteur ne dit pas la voix d'un autre.
   *
   *   filters: [ WamaModelCaps.cloneVoiceFilter('voice_preset') ]
   */
  function engineVoiceOf(opt) {
    return (opt && opt.dataset && opt.dataset.model) || '';
  }

  function cloneVoiceFilter(selectId, opts) {
    opts = opts || {};
    const raison = opts.languageReason
      || 'Cette voix est dans une langue que le moteur ne parle pas : le timbre sera '
         + 'cloné, mais la prononciation de cette langue n\'est pas garantie.';
    return {
      selectId: selectId,
      hideOption: function (caps, opt, key) {
        const owner = engineVoiceOf(opt);
        if (owner) return owner !== key;
        // Une voix de RÉFÉRENCE (`sa_`, un enregistrement de la médiathèque) n'est dite que par
        // un moteur qui clone, comme une voix clonée : le serveur ne la transmet à aucun autre
        // (`voice_refs.speaker_wav_for`). L'offrir sous Kokoro ou Phonon promettait une voix et
        // rendait celle de la langue (vu à l'écran le 2026-10-28, 17 voix sans effet).
        return caps.supports_cloning === false
               && (isClonedVoice(opt.value) || /^sa_/.test(String(opt.value || '')));
      },
      hideWithoutCaps: function (opt) { return !!engineVoiceOf(opt); },
      annotateOption: function (caps, opt) {
        const lang = opt.dataset ? opt.dataset.language : '';
        const langs = Array.isArray(caps.languages) ? caps.languages : [];
        if (!lang || !langs.length || langs.indexOf('*') !== -1) return null;
        if (langs.indexOf(lang) !== -1) return null;
        if ((caps.fallback_languages || []).indexOf(lang) !== -1) return null;
        return raison;
      },
    };
  }

  /*
   * L'OPTION de voix que désigne un asset de la médiathèque (2026-09-30) — ce que rend la
   * fenêtre commune de sélection (`MediaPicker`, `api_list`) traduit dans le vocabulaire du
   * champ voix (`common/utils/voice_options.get_voice_groups`) :
   *   asset SYSTÈME            → `sa_<id>`, groupe `reference` ;
   *   asset d'un utilisateur   → `ua_<id>`, groupe `mine` (le mien) ou `shared` (« nom — propriétaire »).
   * Jumeau de `get_voice_groups` côté serveur : mêmes préfixes, mêmes clés de groupe, même libellé
   * d'une voix d'autrui. `WamaParams` s'en sert pour tout champ `options_source: 'voices'`.
   */
  function voiceOptionFor(asset) {
    if (!asset || asset.id == null) return null;
    if (asset.origin === 'system') {
      return { value: 'sa_' + asset.id, group: 'reference', groupLabel: 'Voix de référence',
               label: asset.name || ('sa_' + asset.id) };
    }
    const shared = asset.origin === 'shared';
    return { value: 'ua_' + asset.id, group: shared ? 'shared' : 'mine',
             groupLabel: shared ? 'Voix partagées' : 'Mes voix (clonage)',
             label: shared ? (asset.name + ' — ' + (asset.owner || '')) : asset.name,
             language: (asset.attributes || {}).language || '' };
  }

  global.WamaModelCaps = { init: init, langFilter: langFilter, applyOptionFilter: applyOptionFilter,
                           cloneVoiceFilter: cloneVoiceFilter, isClonedVoice: isClonedVoice,
                           voiceOptionFor: voiceOptionFor };
})(window);
