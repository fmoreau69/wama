/*
 * wama-params.js — WamaParams : champs ÉDITABLES (réglages) d'une app dans toutes les surfaces
 * (modale item/batch, volet inspecteur) à partir d'un schéma (cf. params.py / param_schema.py).
 * Famille inspecteur : WamaInspector (panneau) · WamaParams (CE FICHIER, ÉDITABLE) · WamaDetails (READ-ONLY).
 *
 * But : une seule source → fin des divergences modale↔volet (markup dupliqué par template).
 * Le `context` gère les différences : 'item'/'batch' → inputs avec `name=` (POST de formulaire) ;
 * 'panel' → inputs avec `data-param=` (lus/écrits par l'inspecteur, pas de POST).
 *
 * API :
 *   WamaParams.render(container, schema, { context, values, optionsResolver })
 *   WamaParams.read(container)            -> { name: value }
 *   WamaParams.apply(container, values)   -> applique des valeurs
 *
 *   schema           : [ {name,type,label,help,default,choices,min,max,step,
 *                         contexts,options_source,show_if,advanced} ]  (Param.to_dict())
 *   optionsResolver  : (param) -> [ {value,label}, … ]  pour les options dynamiques
 *                      (param.options_source, ex. 'backends'). Optionnel.
 */
(function (global) {
  'use strict';

  function esc(s) {
    return (s == null ? '' : String(s)).replace(/[&<>"']/g, function (m) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m];
    });
  }

  // Attribut d'identité selon le contexte : name= (POST modale) ou data-param= (volet).
  function idAttr(ctx, name) {
    return ctx === 'panel' ? ('data-param="' + esc(name) + '"') : ('name="' + esc(name) + '"');
  }

  function optionsFor(p, resolver) {
    if (p.options_source && typeof resolver === 'function') {
      try { return resolver(p) || []; } catch (e) { return []; }
    }
    return (p.choices || []).map(function (c) { return { value: c[0], label: c[1] }; });
  }

  // Contenu d'un <select> : gère le PLAT et les GROUPES (optgroup).
  // Source des groupes : (1) resolver renvoyant [{group, options:[{value,label}]}] (dynamique,
  // ex. voix par utilisateur), ou (2) p.option_groups statique [[libellé,[[v,l]]]].
  function selectInnerHtml(p, v, resolver) {
    function optEl(o) {
      const sel = (String(o.value) === String(v)) ? ' selected' : '';
      return '<option value="' + esc(o.value) + '"' + sel + '>' + esc(o.label) + '</option>';
    }
    let data = null;
    if (p.options_source && typeof resolver === 'function') {
      try { data = resolver(p); } catch (e) { data = null; }
    }
    if (data == null && p.option_groups) {
      data = p.option_groups.map(function (g) {
        return { group: g[0], options: (g[1] || []).map(function (c) { return { value: c[0], label: c[1] }; }) };
      });
    }
    if (data == null) {
      data = (p.choices || []).map(function (c) { return { value: c[0], label: c[1] }; });
    }
    const grouped = Array.isArray(data) && data.length && data[0] && data[0].options;
    if (grouped) {
      return data.map(function (g) {
        return '<optgroup label="' + esc(g.group || '') + '">' +
          (g.options || []).map(optEl).join('') + '</optgroup>';
      }).join('');
    }
    return (data || []).map(optEl).join('');
  }

  // dom_id / radio_name peuvent être une string (toutes surfaces) OU un objet { ctx: id }
  // pour scoper l'ID legacy PAR contexte (ex. panel='backendSelect', item='settingsBackend')
  // → on rend les DEUX surfaces depuis le même schéma sans collision d'ID dans la page.
  function perCtx(v, ctx) {
    if (v && typeof v === 'object') return v[ctx] || '';
    return v || '';
  }

  // ──────────────────────────────────────────────────────────────────────────────────────────
  // REGISTRY DE RENDERERS — vocabulaire FERMÉ de composants, mais EXTENSIBLE sans toucher au
  // moteur. Remplace la cascade `if (p.type === 'select') … else if (p.type === 'range') …` :
  // ajouter un type de champ était jusqu'ici une ÉDITION DE CE FICHIER COMMUN, donc impossible
  // depuis le codegen (templates_gen génère pourtant déjà l'appel à WamaParams.render) comme
  // depuis une app. Le déterminisme est INTACT : un schéma ne peut référencer qu'un type
  // ENREGISTRÉ (sinon repli texte), seule l'indirection change.
  //
  //   WamaParams.registerRenderer('mon-type', function (p, api) { return '<…>'; }, { … });
  //
  // Le renderer reçoit le param `p` (Param.to_dict()) et une `api` — TOUT ce dont il a besoin,
  // pour qu'un renderer défini HORS de ce fichier ait exactement les mêmes moyens qu'un natif :
  //   api.id        identifiant DOM résolu (dom_id legacy ou 'wp-{ctx}-{name}')
  //   api.idAttr    attribut d'identité PRÊT À POSER — name="…" (modale) ou data-param="…" (volet)
  //   api.ctx       'item' | 'batch' | 'panel'
  //   api.value     valeur courante (déjà repliée sur p.default)
  //   api.helpEl    <small> d'aide déjà rendu (help_html brut / help échappé)
  //   api.esc       échappement HTML — À UTILISER pour toute valeur venant du schéma
  //   api.options(p)            options plates [{value,label}] (choices ou optionsResolver)
  //   api.selectOptionsHtml(p)  <option>/<optgroup> prêts (plat ou groupé)
  //
  // Drapeaux (3ᵉ argument) — ce sont les CAPACITÉS du type, plus des `p.type === …` codés en dur
  // ailleurs dans le moteur (row, aide modèle, options async) :
  //   standalone    : le renderer rend TOUT (label + aide compris) → pas d'enveloppe label/aide
  //   noRow         : pas de <div class="wama-param"> autour (champ invisible)
  //   labelIsBlock  : le libellé est un <div> et non un <label for> (contrôle multi-éléments)
  //   modelHelp     : accepte l'aide MODÈLE dynamique (help_source → WamaModelHelp)
  //   optionSources : accepte le peuplement ASYNC des options (options_source → endpoint)
  const RENDERERS = {};

  function registerRenderer(type, fn, flags) {
    const r = { render: fn };
    if (flags) Object.keys(flags).forEach(function (k) { r[k] = flags[k]; });
    RENDERERS[type] = r;
    return r;
  }

  function rendererFor(type) {
    return RENDERERS[type] || RENDERERS.text;
  }

  // Un TYPE déclare-t-il telle capacité ? (remplace les `p.type === 'select'` du moteur)
  function typeSupports(type, flag) {
    const r = RENDERERS[type];
    return !!(r && r[flag]);
  }

  // ── Renderers natifs (le vocabulaire fermé actuel — HTML inchangé) ─────────────────────────

  // Champ porteur (ex. media_type d'un job) : invisible, mais lisible par read() et par les
  // conditions show_if {field: '<ce nom>'}. Rendu sans wrapper visible (cf. render()).
  registerRenderer('hidden', function (p, api) {
    const v = api.value;
    return '<input type="hidden" id="' + api.id + '" ' + api.idAttr +
      ' value="' + esc(v != null ? v : '') + '">';
  }, { standalone: true, noRow: true });

  registerRenderer('toggle', function (p, api) {
    const id = api.id, idA = api.idAttr, v = api.value;
    const on = (v === true || v === 'true' || v === 1 || v === '1');
    const tic = p.icon ? '<i class="fas ' + esc(p.icon) + ' me-1"></i>' : '';
    // pills=[off,on] : sélecteur segmenté (2 radios btn-check) — read()/show_if voient la même
    // valeur 'true'/'false' qu'un switch (radios de même name → la cochée gagne dans read()).
    if (Array.isArray(p.pills) && p.pills.length === 2) {
      // item : idA porte déjà name="…" (groupe les radios) ; panel : idA = data-param → name explicite.
      const rname = idA.indexOf('name=') === 0 ? '' : ' name="' + id + '-seg"';
      const seg = ['false', 'true'].map(function (val, i) {
        const rid = id + '-' + val;
        const it = p.pills[i];                          // "libellé" ou {label, icon}
        const plab = (it && typeof it === 'object') ? it.label : it;
        const pic = (it && typeof it === 'object' && it.icon)
          ? '<i class="fas ' + esc(it.icon) + ' me-1"></i>' : '';
        return '<input type="radio" class="btn-check" id="' + rid + '" ' + idA + rname +
          ' value="' + val + '"' + ((on ? 'true' : 'false') === val ? ' checked' : '') + '>' +
          '<label class="btn btn-outline-primary" for="' + rid + '">' + pic + esc(plab) + '</label>';
      }).join('');
      return (p.label ? '<div class="form-label small mb-1">' + tic + esc(p.label) + '</div>' : '') +
        '<div class="btn-group wama-param-pills w-100" role="group">' + seg + '</div>' + api.helpEl;
    }
    const checked = on ? 'checked' : '';
    return '<div class="form-check form-switch">' +
      '<input class="form-check-input" type="checkbox" id="' + id + '" ' + idA + ' ' + checked + '>' +
      '<label class="form-check-label" for="' + id + '">' + tic + esc(p.label) + '</label></div>' +
      api.helpEl;   // l'aide du toggle (manquait → bug corrigé)
  }, { standalone: true });

  registerRenderer('select', function (p, api) {
    return '<select class="form-select form-select-sm" id="' + api.id + '" ' + api.idAttr + '>' +
      api.selectOptionsHtml(p) + '</select>';
  }, { modelHelp: true, optionSources: true });

  registerRenderer('radio', function (p, api) {
    // name = groupage des radios (obligatoire) ; radio_name = pont vers le nom legacy si fourni
    // (string ou objet par contexte, comme dom_id).
    const id = api.id, idA = api.idAttr, v = api.value;
    const rname = perCtx(p.radio_name, api.ctx) || id;
    const rcls = p.inline ? 'form-check form-check-inline' : 'form-check';
    return api.options(p).map(function (o, i) {
      const checked = (String(o.value) === String(v)) ? 'checked' : '';
      const rid = id + '-' + i;
      return '<div class="' + rcls + '">' +
        '<input class="form-check-input" type="radio" name="' + rname + '" id="' + rid + '" ' + idA +
        ' value="' + esc(o.value) + '" ' + checked + '>' +
        '<label class="form-check-label" for="' + rid + '">' + esc(o.label) + '</label></div>';
    }).join('');
  }, { labelIsBlock: true });

  registerRenderer('textarea', function (p, api) {
    return '<textarea class="form-control form-control-sm" id="' + api.id + '" ' + api.idAttr +
      ' rows="2">' + esc(api.value) + '</textarea>';
  });

  registerRenderer('number', function (p, api) {
    const attrs = [p.min != null ? 'min="' + p.min + '"' : '',
                   p.max != null ? 'max="' + p.max + '"' : '',
                   p.step != null ? 'step="' + p.step + '"' : ''].join(' ');
    return '<input type="number" class="form-control form-control-sm" id="' + api.id + '" ' +
      api.idAttr + ' value="' + esc(api.value) + '" ' + attrs + '>';
  });

  registerRenderer('range', function (p, api) {
    const id = api.id, idA = api.idAttr, v = api.value;
    const rattrs = [p.min != null ? 'min="' + p.min + '"' : '',
                    p.max != null ? 'max="' + p.max + '"' : '',
                    p.step != null ? 'step="' + p.step + '"' : ''].join(' ');
    // Valeur courante (+ unité déclarée) à droite + bornes SOUS le slider — libellés FORMATÉS
    // min_label/max_label prioritaires sur min/max bruts (P2-bis, cf. volet composer 10s/10min).
    const unit = p.unit || '';
    return '<div class="wama-range">' +
      '<div class="d-flex align-items-center gap-2">' +
      '<input type="range" class="form-range" id="' + id + '" ' + idA + ' value="' + esc(v) + '" ' + rattrs +
      ' data-unit="' + esc(unit) + '"' +
      ' oninput="this.parentNode.querySelector(\'.wama-range-val\').textContent=this.value+(this.dataset.unit||\'\')">' +
      '<span class="wama-range-val small text-muted">' + esc(v) + esc(unit) + '</span></div>' +
      ((p.min != null || p.max != null || p.min_label || p.max_label)
        ? '<div class="d-flex justify-content-between small text-muted" style="margin-top:-4px;opacity:.7">' +
          '<span>' + esc(p.min_label || (p.min != null ? String(p.min) + unit : '')) + '</span>' +
          '<span>' + esc(p.max_label || (p.max != null ? String(p.max) + unit : '')) + '</span></div>'
        : '') +
      '</div>';
  });

  // Repli : type absent du registry → champ texte (comportement historique du `else` final).
  registerRenderer('text', function (p, api) {
    return '<input type="text" class="form-control form-control-sm" id="' + api.id + '" ' +
      api.idAttr + ' value="' + esc(api.value) + '">';
  });

  function controlHtml(p, ctx, value, resolver) {
    // dom_id : pont de MIGRATION — réutilise l'ID legacy d'un volet existant pour ne pas casser
    // le JS qui le référence (read/apply/save/async). Sinon ID schéma-driven 'wp-{ctx}-{name}'.
    const id = perCtx(p.dom_id, ctx) || ('wp-' + ctx + '-' + p.name);
    const idA = idAttr(ctx, p.name);
    const v = (value !== undefined && value !== null) ? value : p.default;

    // Aide : help_html (brut, ex. lien modal) prime sur help (échappé). Réutilisé par TOUS les types.
    const helpEl = p.help_html
      ? '<small class="text-muted d-block">' + p.help_html + '</small>'
      : (p.help ? '<small class="text-muted d-block">' + esc(p.help) + '</small>' : '');

    const api = {
      id: id, idAttr: idA, ctx: ctx, value: v, resolver: resolver, helpEl: helpEl, esc: esc,
      options: function (pp) { return optionsFor(pp || p, resolver); },
      selectOptionsHtml: function (pp, vv) {
        return selectInnerHtml(pp || p, vv !== undefined ? vv : v, resolver);
      }
    };

    const r = rendererFor(p.type);
    const inner = r.render(p, api);
    if (r.standalone) return inner;   // le renderer a rendu son libellé et son aide lui-même

    // Icône optionnelle (déclarée dans le schéma) — STRUCTURE seulement ; le look reste en CSS.
    const ic = p.icon ? '<i class="fas ' + esc(p.icon) + ' me-1"></i>' : '';
    const label = !p.label
      ? ''   // pas de label déclaré → on n'en rend aucun (évite un libellé vide/redondant)
      : (r.labelIsBlock
          ? '<div class="form-label small mb-1">' + ic + esc(p.label) + '</div>'
          : '<label class="form-label small mb-1" for="' + id + '">' + ic + esc(p.label) + '</label>');
    // Aide MODÈLE dynamique (desc courte + ⓘ longue + VRAM) : placeholder rempli par WamaModelHelp
    // dans render() pour les types qui déclarent la capacité `modelHelp` (catalogue model_manager).
    const modelHelp = (r.modelHelp && (p.help_source || p.help_fallback))
      ? '<div class="wama-model-help small text-muted mt-1" id="' + id + '-help"></div>' : '';
    return label + inner + helpEl + modelHelp;
  }

  function _showIfAttr(cond) {
    if (!cond) return '';
    return ' data-show-if="' + esc(typeof cond === 'string' ? cond : JSON.stringify(cond)) + '"';
  }

  // Enveloppe d'un groupe déclaré (ParamGroup) : titre + corps ; show_if de GROUPE géré par
  // _bindConditional comme celui d'un champ ; collapsed → <details> natif (zéro JS).
  function _groupWrap(meta, inner) {
    if (!inner) return '';
    const ic = meta.icon ? '<i class="fas ' + esc(meta.icon) + ' me-1"></i>' : '';
    const title = ic + esc(meta.title || '');
    const attrs = ' data-group="' + esc(meta.key) + '"' + _showIfAttr(meta.show_if);
    const body = 'wama-param-group-body' + (meta.columns === 2 ? ' wama-param-group-cols-2' : '');
    if (meta.collapsed) {
      return '<details class="wama-param-group"' + attrs + '>' +
        '<summary class="wama-param-group-title">' + title + '</summary>' +
        '<div class="' + body + '">' + inner + '</div></details>';
    }
    return '<div class="wama-param-group"' + attrs + '>' +
      '<div class="wama-param-group-title">' + title + '</div>' +
      '<div class="' + body + '">' + inner + '</div></div>';
  }

  function render(container, schema, opts) {
    if (!container) return;
    opts = opts || {};
    const ctx = opts.context || 'panel';
    const values = opts.values || {};
    const resolver = opts.optionsResolver;

    const params = (schema || []).filter(function (p) {
      return !p.contexts || p.contexts.indexOf(ctx) !== -1;
    });
    function rowHtml(p) {
      const value = (p.name in values) ? values[p.name] : undefined;
      // Types `noRow` (hidden) : input nu, sans wrapper visible (pas de marge/label).
      if (typeSupports(p.type, 'noRow')) return controlHtml(p, ctx, value, resolver);
      return '<div class="wama-param mb-2" data-param-row="' + esc(p.name) + '"' +
        _showIfAttr(p.show_if) +
        (p.advanced ? ' data-advanced="1"' : '') + '>' +
        controlHtml(p, ctx, value, resolver) + '</div>';
    }

    let html;
    if (Array.isArray(opts.groups) && opts.groups.length) {
      // Rendu par GROUPES déclarés (ParamGroup) : 1) champs hors groupe non avancés (ordre schéma),
      // 2) groupes dans l'ordre déclaré, 3) avancés sans groupe → groupe implicite « Avancé » replié.
      const byGroup = {};
      const flat = [], adv = [];
      params.forEach(function (p) {
        if (p.group) (byGroup[p.group] = byGroup[p.group] || []).push(p);
        else if (p.advanced && p.type !== 'hidden') adv.push(p);
        else flat.push(p);
      });
      html = flat.map(rowHtml).join('') +
        opts.groups.map(function (meta) {
          return _groupWrap(meta, (byGroup[meta.key] || []).map(rowHtml).join(''));
        }).join('') +
        _groupWrap({ key: '_advanced', title: opts.advancedTitle || 'Avancé',
                     icon: 'fa-sliders', collapsed: true },
                   adv.map(rowHtml).join(''));
    } else {
      html = params.map(rowHtml).join('');
    }

    container.innerHTML = html;
    _bindConditional(container);
    _bindModelHelp(container, schema, ctx);
    _bindOptionSources(container, schema, ctx);
  }

  // Sources d'options ASYNC centralisées (manifeste) : options_source → endpoint renvoyant {groups}.
  // Ex. 'voices' → /common/api/voices/ (peuple les optgroups voix sans markup serveur par app).
  // Surchageable via window.WAMA_OPTION_SOURCES. Si la clé n'est pas connue ici, l'app fournit un
  // optionsResolver synchrone à la place (rétro-compatible).
  // `catalog` (2026-08-31, route F4b) : les options d'un select de MODÈLE viennent du
  // CATALOGUE, plus d'une liste écrite dans l'app. Le domaine se déclare au schéma via
  // `options_query` (cf. ci-dessous) — sans quoi une clé, qui ne porte qu'une URL fixe,
  // ne saurait pas DE QUOI parler.
  var OPTION_SOURCES = global.WAMA_OPTION_SOURCES || {
    voices: '/common/api/voices/',
    catalog: '/model-manager/api/models/options/',
  };
  var _optionSourceCache = {};

  // Querystring déclarée au schéma : `options_query: {task: 'text-to-speech'}`.
  // ⚠ Ce qui a le droit d'y figurer borne le DOMAINE (task / model_type / modality /
  // source) — jamais les entrées fournies ni les capacités requises : celles-là GRISENT
  // côté client (WamaInputMatch/WamaModelCaps) sur la liste complète, elles n'excluent
  // pas côté serveur. Lister n'est pas pouvoir choisir (INPUT_MODEL_MATCHING §2).
  function _optionQuery(p) {
    var q = p.options_query;
    if (!q || typeof q !== 'object') return '';
    var parts = Object.keys(q).sort().filter(function (k) {
      return q[k] !== null && q[k] !== undefined && q[k] !== '';
    }).map(function (k) {
      return encodeURIComponent(k) + '=' + encodeURIComponent(q[k]);
    });
    return parts.length ? ('?' + parts.join('&')) : '';
  }

  function _bindOptionSources(container, schema, ctx) {
    (schema || []).forEach(function (p) {
      if (!typeSupports(p.type, 'optionSources') || !p.options_source) return;
      if (p.contexts && p.contexts.indexOf(ctx) === -1) return;
      var url = OPTION_SOURCES[p.options_source];
      if (!url) return;   // pas d'endpoint connu → l'app gère via optionsResolver (rendu synchrone)
      // La querystring fait partie de l'URL — donc aussi de la CLÉ DE CACHE : deux domaines
      // distincts sur la même page (ex. un select TTS et un select ASR) ne doivent pas se
      // servir mutuellement leur liste.
      url += _optionQuery(p);
      var sid = perCtx(p.dom_id, ctx) || ('wp-' + ctx + '-' + p.name);
      var sel = document.getElementById(sid);
      if (!sel) return;
      var fill = function (groups) {
        var cur = sel.value;
        sel.innerHTML = (groups || []).map(function (g) {
          var opts = (g.options || []).map(function (o) {
            var v = Array.isArray(o) ? o[0] : (o.value !== undefined ? o.value : o[0]);
            var l = Array.isArray(o) ? o[1] : (o.label !== undefined ? o.label : o[1]);
            return '<option value="' + esc(v) + '">' + esc(l) + '</option>';
          }).join('');
          return g.group ? ('<optgroup label="' + esc(g.group) + '">' + opts + '</optgroup>') : opts;
        }).join('');
        if (cur) sel.value = cur;
        sel.dispatchEvent(new Event('change', { bubbles: true }));   // re-déclenche WamaModelCaps/conditionnel
      };
      if (_optionSourceCache[url]) { fill(_optionSourceCache[url]); return; }
      fetch(url, { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (d) { _optionSourceCache[url] = d.groups || []; fill(_optionSourceCache[url]); })
        .catch(function () {});
    });
  }

  // ── Sources d'options adossées à une DONNÉE DE PAGE (résolution SYNCHRONE) ──────────────
  //
  // Deuxième famille de sources, à côté des endpoints ci-dessus. `options_source` déclare une
  // CLÉ ; les clés de `OPTION_SOURCES` se résolvent par un GET, celles-ci par une donnée déjà
  // posée sur la page. Sans ce registre, une clé de la seconde famille n'était résoluble que
  // par un resolver écrit à la main dans l'app — donc introuvable pour un GÉNÉRATEUR, qui
  // rendait un select vide ou un avertissement (« options « formats » non déclarées », relevé
  // sur la jumelle converter_01 le 2026-08-29 : plus aucun format de sortie proposé, donc rien
  // de lançable).
  //
  // ⚠ J'ai d'abord écrit que c'était un TROU DU FORMALISME — « rien, ni dans Param ni au
  // manifeste, ne dit d'où viennent ces options ». C'était faux pour `formats`, et faux de la
  // même façon que deux autres fois cette semaine : j'ai annoncé un trou avant d'avoir cherché
  // la déclaration. `CONVERTER_OUTPUT_FORMATS` est exposé à TOUTES les pages depuis
  // `accounts/context_processors.py` (processeur global) — la donnée était là, sur chaque
  // rendu, depuis longtemps. *Un trou constaté sans avoir cherché l'accesseur est une
  // hypothèse déguisée en mesure.*
  //
  // Une source de cette famille se DÉCLARE ici (registre commun), jamais dans une app :
  // `values` = valeurs courantes du formulaire, car une source peut en dépendre (les formats de
  // sortie dépendent de la nature du média de l'élément).
  var PAGE_OPTION_SOURCES = {
    // `formats` : formats de sortie du converter par type de média — la table de conversion de
    // la plateforme (`CONVERTER_OUTPUT_FORMATS`), pas une donnée d'app. Même rendu que le
    // resolver historique du converter (`converter.js`) : « — inchangé — » puis « .PNG ».
    formats: function (values) {
      var table = global.WAMA_OUTPUT_FORMATS || {};
      var mt = (values || {}).media_type;
      var liste = table[mt] || [];
      if (!mt) {
        // Sans media_type connu (hôte du volet rendu au CHARGEMENT, avant toute sélection) :
        // UNION des familles — même choix que le panel historique du converter (le media_type
        // varie par card inspectée, le select doit pouvoir AFFICHER la valeur de chacune ;
        // le show_if par media_type fait le tri). Une liste vide ici laissait le select du
        // volet sans aucun format, donc l'apply de la sélection sans option à montrer.
        var seen = {};
        liste = [];
        Object.keys(table).forEach(function (k) {
          (table[k] || []).forEach(function (f) {
            if (!seen[f]) { seen[f] = 1; liste.push(f); }
          });
        });
      }
      return [{ value: '', label: '— inchangé —' }].concat(liste.map(function (f) {
        return { value: f, label: '.' + String(f).toUpperCase() };
      }));
    },
  };

  // (param, valeurs) -> options plates, ou null si la clé n'appartient pas à cette famille.
  // Renvoyer null (et non []) est ce qui laisse l'appelant distinguer « pas ma famille » de
  // « ma famille, mais rien à proposer » — la distinction que le select vide effaçait.
  function resolvePageOptions(p, values) {
    if (!p || !p.options_source) return null;
    var reg = global.WAMA_PAGE_OPTION_SOURCES || PAGE_OPTION_SOURCES;
    var f = reg[p.options_source];
    return f ? f(values || {}, p) : null;
  }

  // Aide MODÈLE : pour chaque select déclarant help_source, câble WamaModelHelp (desc courte + ⓘ longue
  // + VRAM) depuis le catalogue model_manager (fetchCatalogMeta). Métadonnée-driven, zéro JS par app.
  function _bindModelHelp(container, schema, ctx) {
    if (!global.WamaModelHelp) return;
    (schema || []).forEach(function (p) {
      if (!typeSupports(p.type, 'modelHelp') || (!p.help_source && !p.help_fallback)) return;
      if (p.contexts && p.contexts.indexOf(ctx) === -1) return;
      const sid = perCtx(p.dom_id, ctx) || ('wp-' + ctx + '-' + p.name);
      if (!document.getElementById(sid + '-help')) return;
      const cfg = { selectId: sid, helpId: sid + '-help', fallback: p.help_fallback || {} };
      if (p.help_source) {
        Promise.resolve(global.WamaModelHelp.fetchCatalogMeta(p.help_source)).then(function (meta) {
          cfg.meta = meta || {}; global.WamaModelHelp.init(cfg);
        }).catch(function () { cfg.meta = {}; global.WamaModelHelp.init(cfg); });
      } else {
        cfg.meta = {}; global.WamaModelHelp.init(cfg);   // pas de catalogue → repli seul
      }
    });
  }

  // Visibilité conditionnelle (show_if) : un toggle pilote l'affichage d'autres champs.
  function _bindConditional(container) {
    // Valeur courante d'un champ par nom (toggle/select/radio/text), DANS ce conteneur.
    function valByName(name) {
      let val;
      container.querySelectorAll('[name],[data-param]').forEach(function (el) {
        const n = el.getAttribute('name') || el.getAttribute('data-param');
        if (n !== name) return;
        if (el.type === 'checkbox') val = el.checked;
        else if (el.type === 'radio') { if (el.checked) val = el.value; }
        else val = el.value;
      });
      return val;
    }
    // show_if : string « <champ> » (truthy) OU JSON {field, in:[…] | equals:… }.
    function parseCond(raw) {
      if (!raw) return null;
      try { const o = JSON.parse(raw); if (o && typeof o === 'object') return o; } catch (e) {}
      return { field: raw };   // legacy : nom de champ, condition = truthy
    }
    function met(cond) {
      const cur = valByName(cond.field);
      if (cond.in) return cond.in.map(String).indexOf(String(cur)) !== -1;
      if ('equals' in cond) return String(cur) === String(cond.equals);
      return !!cur && cur !== 'false' && cur !== '0';   // défaut : truthy
    }
    function apply() {
      container.querySelectorAll('[data-show-if]').forEach(function (row) {
        const cond = parseCond(row.getAttribute('data-show-if'));
        row.style.display = (cond && met(cond)) ? '' : 'none';
      });
    }
    apply();
    // Un seul écouteur délégué, lié UNE fois par conteneur (apply re-interroge le DOM vivant →
    // reste correct après un re-render). Évite l'accumulation d'écouteurs au re-render.
    if (!container._wpCondBound) {
      container._wpCondBound = true;
      container.addEventListener('change', function () { apply(); });
      container.addEventListener('input', function () { apply(); });
    }
  }

  function _fieldValue(el) {
    if (el.type === 'checkbox') return el.checked;
    return el.value;
  }

  function read(container) {
    const out = {};
    if (!container) return out;
    // radios : une seule valeur par nom ; on prend la cochée.
    container.querySelectorAll('[name],[data-param]').forEach(function (el) {
      const n = el.getAttribute('name') || el.getAttribute('data-param');
      if (el.type === 'radio') { if (el.checked) out[n] = el.value; }
      else out[n] = _fieldValue(el);
    });
    return out;
  }

  function apply(container, values) {
    if (!container || !values) return;
    container.querySelectorAll('[name],[data-param]').forEach(function (el) {
      const n = el.getAttribute('name') || el.getAttribute('data-param');
      if (!(n in values)) return;
      const v = values[n];
      if (el.type === 'checkbox') el.checked = (v === true || v === 'true' || v === 1 || v === '1');
      else if (el.type === 'radio') el.checked = (String(el.value) === String(v));
      else el.value = v;
    });
    // Re-sync l'affichage des sliders (range) : un set programmatique ne déclenche pas l'oninput.
    container.querySelectorAll('.wama-range').forEach(function (r) {
      const inp = r.querySelector('input[type="range"]');
      const span = r.querySelector('.wama-range-val');
      if (inp && span) span.textContent = inp.value;
    });
    _bindConditional(container);
  }

  // ── Coquille de modale « Paramètres » GÉNÉRÉE (brique commune) ────────────────────────────
  // Extrait du pattern DÉJÀ automatisé d'enhancer/reader (createSettingsModal) — cf.
  // UI_MECHANISMS_CONSOLIDATION §5/§9 (P1) : coquille (wrapper/header/body/footer) + CHAMPS
  // rendus par render() depuis le schéma params.py, en une seule source. Le câblage des
  // boutons reste à l'appelant (délégation par classes/data-*, inchangée par app).
  //
  //   WamaParams.renderSettingsModal({
  //     id,        // suffixe unique — modale par-item (enhancer) ou nom fixe (modale partagée)
  //     title,     // texte du header (échappé ici)
  //     titleIcon, // classe FA optionnelle (ex. 'fa-gear')
  //     schema, values,      // → render(host, schema, {context, values})
  //     context,   // contexte de rendu du schéma — défaut 'item' ; 'batch' pour la modale
  //                // de LOT (mêmes briques, seuls les params déclarant 'batch' se rendent)
  //     formClass, formData, // <form> : classe + data-* (délégation existante des apps)
  //     buttons,   // [{label, className, icon?, data?}] — défaut : Annuler + Enregistrer
  //   }) → { modal, host, form }   (remplace la modale existante de même id)
  function renderSettingsModal(cfg) {
    cfg = cfg || {};
    const esc = function (s) {
      return String(s == null ? '' : s).replace(/[&<>"']/g, function (m) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m];
      });
    };
    const modalId = 'settingsModal' + (cfg.id != null ? cfg.id : '');
    const old = document.getElementById(modalId);
    if (old) old.remove();

    const buttons = cfg.buttons || [
      { label: 'Annuler', className: 'btn btn-secondary', data: { 'bs-dismiss': 'modal' } },
      { label: 'Enregistrer', className: 'btn btn-primary save-settings-btn' },
    ];
    const btnHtml = buttons.map(function (b) {
      const data = Object.keys(b.data || {}).map(function (k) {
        return ' data-' + k + '="' + esc(b.data[k]) + '"';
      }).join('');
      const icon = b.icon ? '<i class="fas ' + esc(b.icon) + '"></i> ' : '';
      return '<button type="button" class="' + esc(b.className || 'btn btn-secondary') + '"' +
             data + '>' + icon + esc(b.label) + '</button>';
    }).join('\n            ');

    const modal = document.createElement('div');
    modal.className = 'modal fade';
    modal.id = modalId;
    modal.setAttribute('tabindex', '-1');
    modal.innerHTML =
      '<div class="modal-dialog modal-dialog-centered">' +
      '  <div class="modal-content bg-dark text-white border-secondary">' +
      '    <div class="modal-header border-secondary">' +
      '      <h5 class="modal-title">' +
      (cfg.titleIcon ? '<i class="fas ' + esc(cfg.titleIcon) + ' me-2"></i>' : '') +
      esc(cfg.title || 'Paramètres') + '</h5>' +
      '      <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>' +
      '    </div>' +
      '    <div class="modal-body">' +
      '      <form class="' + esc(cfg.formClass || '') + '">' +
      '        <div class="wama-params wama-modal-fields"></div>' +
      '      </form>' +
      '    </div>' +
      '    <div class="modal-footer border-secondary">' +
      '      ' + btnHtml +
      '    </div>' +
      '  </div>' +
      '</div>';
    document.body.appendChild(modal);

    const form = modal.querySelector('form');
    Object.keys(cfg.formData || {}).forEach(function (k) {
      form.setAttribute('data-' + k, cfg.formData[k]);
    });
    const host = modal.querySelector('.wama-modal-fields');
    if (cfg.schema) render(host, cfg.schema, { context: cfg.context || 'item', values: cfg.values || {},
                                               groups: cfg.groups, optionsResolver: cfg.optionsResolver });
    return { modal: modal, host: host, form: form };
  }

  // ── Modale de réglages d'item : ORCHESTRATION commune ──────────────────────
  // `renderSettingsModal` ne fait que le MARKUP. Le cycle complet (charger les valeurs →
  // rendre → greffer le pied → afficher → lire → enregistrer → enchaîner) était recopié
  // par app (anonymizer, puis imager) : mêmes fonctions, mêmes noms, même ordre. Il vit
  // ici, les spécificités restent des HOOKS déclarés par l'app.
  //
  // cfg = {
  //   id, title, titleIcon, schema, groups, formClass,   // → renderSettingsModal
  //   fetchUrl,            // GET → JSON des valeurs (sinon passer `values`)
  //   values,              // valeurs déjà connues (alternative à fetchUrl)
  //   saveUrl, csrf,       // POST FormData
  //   footerTplId,         // <template> du pied commun (_settings_modal_footer.html)
  //   idField,             // nom du champ id à poster (défaut : aucun)
  //   decorate(host, data, ctx),   // zones d'app HORS schéma (prompt, présets, aperçus…)
  //   collect(fd, host, data, restart),  // champs d'app à ajouter au POST — `restart` est
  //                                      // fourni car certaines apps le postent (anonymizer)
  //                                      // au lieu d'enchaîner un second appel (imager)
  //   onSaved(id, restart, resp),  // suite (rafraîchir la card, relancer…)
  //   errorOf(resp),               // extraction du message d'erreur (défaut : resp.error)
  // }
  function settingsModal(cfg) {
    cfg = cfg || {};
    const toast = function (m, t) {
      if (global.WamaApp && WamaApp.toast) WamaApp.toast(m, t || 'info');
    };

    function graftFooter(modal) {
      const tpl = cfg.footerTplId && document.getElementById(cfg.footerTplId);
      if (!tpl || !tpl.content || !tpl.content.firstElementChild) return;
      const foot = tpl.content.firstElementChild.cloneNode(true);
      const old = modal.querySelector('.modal-footer');
      if (old) old.replaceWith(foot);
    }

    function build(data) {
      const res = renderSettingsModal({
        id: cfg.id, title: cfg.title, titleIcon: cfg.titleIcon,
        schema: cfg.schema || [], groups: cfg.groups || [],
        values: data || {}, formClass: cfg.formClass, context: cfg.context,
        optionsResolver: cfg.optionsResolver,
      });
      const modal = res.modal, host = res.host;
      modal.dataset.wamaItemId = cfg.id;
      graftFooter(modal);
      if (typeof cfg.decorate === 'function') cfg.decorate(host, data || {}, res);

      // Délégation locale À LA MODALE (pas au document) : pas d'accumulation de
      // listeners quand la modale est rouverte sur un autre item.
      modal.addEventListener('click', function (e) {
        const save = e.target.closest('.save-settings-btn');
        const restart = e.target.closest('.save-and-restart-btn');
        if (save || restart) doSave(modal, host, data || {}, !!restart);
      });

      new bootstrap.Modal(modal).show();
      return res;
    }

    function doSave(modal, host, data, restart) {
      const fd = new FormData();
      const vals = read(host);
      Object.keys(vals).forEach(function (k) { fd.append(k, vals[k]); });
      if (cfg.idField) fd.append(cfg.idField, cfg.id);
      if (cfg.csrf) fd.append('csrfmiddlewaretoken', cfg.csrf);
      if (typeof cfg.collect === 'function') cfg.collect(fd, host, data, restart);

      const send = (global.WamaApp && WamaApp.csrfFetch)
        ? WamaApp.csrfFetch(cfg.saveUrl, cfg.csrf, { method: 'POST', body: fd })
        : fetch(cfg.saveUrl, { method: 'POST', body: fd });

      return send
        .then(function (r) { return r.json().catch(function () { return {}; }); })
        .then(function (resp) {
          const err = (typeof cfg.errorOf === 'function') ? cfg.errorOf(resp) : resp.error;
          if (err) { toast(err, 'error'); return; }
          const inst = bootstrap.Modal.getInstance(modal);
          if (inst) inst.hide();
          toast('Paramètres enregistrés', 'success');
          if (typeof cfg.onSaved === 'function') cfg.onSaved(cfg.id, restart, resp);
        })
        .catch(function () { toast("Erreur réseau à l'enregistrement", 'error'); });
    }

    if (cfg.values) return Promise.resolve(build(cfg.values));
    return fetch(cfg.fetchUrl)
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(build)
      .catch(function () { toast('Impossible de charger les paramètres', 'error'); });
  }

  global.WamaParams = { render: render, read: read, apply: apply,
                        renderSettingsModal: renderSettingsModal,
                        settingsModal: settingsModal,
                        // Extension du vocabulaire de composants SANS toucher au moteur :
                        // un type absent du registry retombe sur le champ texte (jamais d'erreur).
                        registerRenderer: registerRenderer,
                        // Sources d'options adossées à une donnée de page (cf. PAGE_OPTION_SOURCES) —
                        // exposé pour qu'un optionsResolver (d'app ou GÉNÉRÉ) délègue au registre
                        // commun au lieu de réécrire la même résolution.
                        resolvePageOptions: resolvePageOptions,
                        rendererTypes: function () { return Object.keys(RENDERERS); } };
})(window);
