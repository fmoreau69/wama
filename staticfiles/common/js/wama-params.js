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

    if (p.type === 'hidden') {
      // Champ porteur (ex. media_type d'un job) : invisible, mais lisible par read() et par les
      // conditions show_if {field: '<ce nom>'}. Rendu sans wrapper visible (cf. render()).
      return '<input type="hidden" id="' + id + '" ' + idA + ' value="' + esc(v != null ? v : '') + '">';
    }

    if (p.type === 'toggle') {
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
          '<div class="btn-group wama-param-pills w-100" role="group">' + seg + '</div>' + helpEl;
      }
      const checked = on ? 'checked' : '';
      return '<div class="form-check form-switch">' +
        '<input class="form-check-input" type="checkbox" id="' + id + '" ' + idA + ' ' + checked + '>' +
        '<label class="form-check-label" for="' + id + '">' + tic + esc(p.label) + '</label></div>' +
        helpEl;   // l'aide du toggle (manquait → bug corrigé)
    }

    let inner;
    if (p.type === 'select') {
      inner = '<select class="form-select form-select-sm" id="' + id + '" ' + idA + '>' +
        selectInnerHtml(p, v, resolver) + '</select>';
    } else if (p.type === 'radio') {
      // name = groupage des radios (obligatoire) ; radio_name = pont vers le nom legacy si fourni
      // (string ou objet par contexte, comme dom_id).
      const rname = perCtx(p.radio_name, ctx) || id;
      const rcls = p.inline ? 'form-check form-check-inline' : 'form-check';
      inner = optionsFor(p, resolver).map(function (o, i) {
        const checked = (String(o.value) === String(v)) ? 'checked' : '';
        const rid = id + '-' + i;
        return '<div class="' + rcls + '">' +
          '<input class="form-check-input" type="radio" name="' + rname + '" id="' + rid + '" ' + idA +
          ' value="' + esc(o.value) + '" ' + checked + '>' +
          '<label class="form-check-label" for="' + rid + '">' + esc(o.label) + '</label></div>';
      }).join('');
    } else if (p.type === 'textarea') {
      inner = '<textarea class="form-control form-control-sm" id="' + id + '" ' + idA + ' rows="2">' +
        esc(v) + '</textarea>';
    } else if (p.type === 'number') {
      const attrs = [p.min != null ? 'min="' + p.min + '"' : '',
                     p.max != null ? 'max="' + p.max + '"' : '',
                     p.step != null ? 'step="' + p.step + '"' : ''].join(' ');
      inner = '<input type="number" class="form-control form-control-sm" id="' + id + '" ' +
        idA + ' value="' + esc(v) + '" ' + attrs + '>';
    } else if (p.type === 'range') {
      const rattrs = [p.min != null ? 'min="' + p.min + '"' : '',
                      p.max != null ? 'max="' + p.max + '"' : '',
                      p.step != null ? 'step="' + p.step + '"' : ''].join(' ');
      // Valeur courante (+ unité déclarée) à droite + bornes SOUS le slider — libellés FORMATÉS
      // min_label/max_label prioritaires sur min/max bruts (P2-bis, cf. volet composer 10s/10min).
      const unit = p.unit || '';
      inner = '<div class="wama-range">' +
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
    } else {
      inner = '<input type="text" class="form-control form-control-sm" id="' + id + '" ' +
        idA + ' value="' + esc(v) + '">';
    }

    // Icône optionnelle (déclarée dans le schéma) — STRUCTURE seulement ; le look reste en CSS.
    const ic = p.icon ? '<i class="fas ' + esc(p.icon) + ' me-1"></i>' : '';
    const label = !p.label
      ? ''   // pas de label déclaré → on n'en rend aucun (évite un libellé vide/redondant)
      : (p.type === 'radio'
          ? '<div class="form-label small mb-1">' + ic + esc(p.label) + '</div>'
          : '<label class="form-label small mb-1" for="' + id + '">' + ic + esc(p.label) + '</label>');
    // Aide MODÈLE dynamique (desc courte + ⓘ longue + VRAM) : placeholder rempli par WamaModelHelp
    // dans render() pour les selects qui déclarent help_source (catalogue model_manager).
    const modelHelp = (p.type === 'select' && (p.help_source || p.help_fallback))
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
      // hidden : input nu, sans wrapper visible (pas de marge/label).
      if (p.type === 'hidden') return controlHtml(p, ctx, value, resolver);
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
  var OPTION_SOURCES = global.WAMA_OPTION_SOURCES || { voices: '/common/api/voices/' };
  var _optionSourceCache = {};
  function _bindOptionSources(container, schema, ctx) {
    (schema || []).forEach(function (p) {
      if (p.type !== 'select' || !p.options_source) return;
      if (p.contexts && p.contexts.indexOf(ctx) === -1) return;
      var url = OPTION_SOURCES[p.options_source];
      if (!url) return;   // pas d'endpoint connu → l'app gère via optionsResolver (rendu synchrone)
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

  // Aide MODÈLE : pour chaque select déclarant help_source, câble WamaModelHelp (desc courte + ⓘ longue
  // + VRAM) depuis le catalogue model_manager (fetchCatalogMeta). Métadonnée-driven, zéro JS par app.
  function _bindModelHelp(container, schema, ctx) {
    if (!global.WamaModelHelp) return;
    (schema || []).forEach(function (p) {
      if (p.type !== 'select' || (!p.help_source && !p.help_fallback)) return;
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
  //     schema, values,      // → render(host, schema, {context:'item', values})
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
    if (cfg.schema) render(host, cfg.schema, { context: 'item', values: cfg.values || {},
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
  //   collect(fd, host, data),     // champs d'app à ajouter au POST
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
        values: data || {}, formClass: cfg.formClass,
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
      if (typeof cfg.collect === 'function') cfg.collect(fd, host, data);

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
                        settingsModal: settingsModal };
})(window);
