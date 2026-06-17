/*
 * wama-params.js — Rendu UNIQUE des paramètres d'une app dans toutes les surfaces
 * (modale item/batch, volet inspecteur) à partir d'un schéma (cf. params.py / param_schema.py).
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

  function controlHtml(p, ctx, value, resolver) {
    const id = 'wp-' + ctx + '-' + p.name;
    const idA = idAttr(ctx, p.name);
    const v = (value !== undefined && value !== null) ? value : p.default;

    if (p.type === 'toggle') {
      const checked = (v === true || v === 'true' || v === 1 || v === '1') ? 'checked' : '';
      return '<div class="form-check form-switch">' +
        '<input class="form-check-input" type="checkbox" id="' + id + '" ' + idA + ' ' + checked + '>' +
        '<label class="form-check-label" for="' + id + '">' + esc(p.label) + '</label></div>';
    }

    let inner;
    if (p.type === 'select') {
      const opts = optionsFor(p, resolver).map(function (o) {
        const sel = (String(o.value) === String(v)) ? 'selected' : '';
        return '<option value="' + esc(o.value) + '" ' + sel + '>' + esc(o.label) + '</option>';
      }).join('');
      inner = '<select class="form-select form-select-sm" id="' + id + '" ' + idA + '>' + opts + '</select>';
    } else if (p.type === 'radio') {
      inner = optionsFor(p, resolver).map(function (o, i) {
        const checked = (String(o.value) === String(v)) ? 'checked' : '';
        const rid = id + '-' + i;
        return '<div class="form-check">' +
          '<input class="form-check-input" type="radio" id="' + rid + '" ' + idA +
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
    } else {
      inner = '<input type="text" class="form-control form-control-sm" id="' + id + '" ' +
        idA + ' value="' + esc(v) + '">';
    }

    const label = (p.type === 'radio')
      ? '<div class="form-label small mb-1">' + esc(p.label) + '</div>'
      : '<label class="form-label small mb-1" for="' + id + '">' + esc(p.label) + '</label>';
    const help = p.help ? '<small class="text-muted d-block">' + esc(p.help) + '</small>' : '';
    return label + inner + help;
  }

  function render(container, schema, opts) {
    if (!container) return;
    opts = opts || {};
    const ctx = opts.context || 'panel';
    const values = opts.values || {};
    const resolver = opts.optionsResolver;

    const rows = (schema || []).filter(function (p) {
      return !p.contexts || p.contexts.indexOf(ctx) !== -1;
    }).map(function (p) {
      const value = (p.name in values) ? values[p.name] : undefined;
      return '<div class="wama-param mb-2" data-param-row="' + esc(p.name) + '"' +
        (p.show_if ? ' data-show-if="' + esc(p.show_if) + '"' : '') +
        (p.advanced ? ' data-advanced="1"' : '') + '>' +
        controlHtml(p, ctx, value, resolver) + '</div>';
    }).join('');

    container.innerHTML = rows;
    _bindConditional(container);
  }

  // Visibilité conditionnelle (show_if) : un toggle pilote l'affichage d'autres champs.
  function _bindConditional(container) {
    const toggles = {};
    container.querySelectorAll('[name],[data-param]').forEach(function (el) {
      const n = el.getAttribute('name') || el.getAttribute('data-param');
      if (el.type === 'checkbox') toggles[n] = el;
    });
    function apply() {
      container.querySelectorAll('[data-show-if]').forEach(function (row) {
        const dep = toggles[row.getAttribute('data-show-if')];
        row.style.display = (dep && dep.checked) ? '' : 'none';
      });
    }
    Object.values(toggles).forEach(function (t) { t.addEventListener('change', apply); });
    apply();
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
    _bindConditional(container);
  }

  global.WamaParams = { render: render, read: read, apply: apply };
})(window);
