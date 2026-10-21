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

  // ⚠ CHAÎNE de résolution (contrat depuis le 2026-09-01) : le resolver rend `null` pour dire
  // « cette clé n'est pas de ma famille » — on CONTINUE alors vers option_groups/choices au
  // lieu de rendre un select vide. Sans ce maillon, poser un resolver PAR DÉFAUT (registre
  // commun, cf. `render`) viderait `transcriber.backend` et les `voice_preset` du synthesizer
  // et de l'avatarizer : trois selects qui portent `options_source` ET des choices de repli
  // (mesuré avant le geste). Un `|| []` avalait cette distinction.
  function optionsFor(p, resolver) {
    if (p.options_source && typeof resolver === 'function') {
      try {
        const r = resolver(p);
        if (r) return r;
      } catch (e) { /* resolver fautif : on retombe sur le statique, jamais d'exception */ }
    }
    return (p.choices || []).map(function (c) { return { value: c[0], label: c[1] }; });
  }

  // UN SEUL rendu d'<option> et d'<optgroup> pour les DEUX chemins — le rendu SYNCHRONE
  // (`selectInnerHtml`) et la recharge ASYNCHRONE (`_bindOptionSources`). Jusqu'au 2026-09-22 ils
  // en avaient chacun un : l'asynchrone savait lire une option en PAIRE `[valeur, libellé]`
  // (la forme de `get_voice_groups`) et en posait les `data-*` ; le synchrone ne lisait que
  // `{value, label}` et ignorait les attributs. Mesuré dans V8 sur le fichier servi : des groupes
  // de voix rendus en synchrone donnaient `<option value="" selected></option>` — valeurs et
  // libellés VIDES, sans `data-language` —, réparés seulement quand la recharge arrivait. Et les
  // filtres qui lisent `data-language` (WamaModelCaps) voyaient, entre-temps, des options nues.
  //   o             : `[valeur, libellé]` OU `{value, label, disabled, title}`
  //   attrsByValue  : `g.attributes` — ce que l'option PORTE (ex. la langue d'une voix) → `data-*`
  //   selectedValue : valeur à présélectionner (le chemin synchrone ; l'asynchrone passe `undefined`)
  function optionHtml(o, attrsByValue, selectedValue) {
    const isPair = Array.isArray(o);
    const value = isPair ? o[0] : (o.value !== undefined ? o.value : o[0]);
    const label = isPair ? o[1] : (o.label !== undefined ? o.label : o[1]);
    // Grisage AUTOMATIQUE serveur (backend absent, 02/09) : l'option reste AFFICHÉE, non
    // sélectionnable, la raison en title — et se ré-autorise toute seule au prochain service.
    // `data-backend-missing` : le VERDICT SERVEUR, que le grisage CLIENT (wama-input-match, qui
    // réécrit disabled/title à chaque change) doit RESPECTER.
    const dis = (!isPair && o.disabled) ? ' disabled' : '';
    const tit = (!isPair && o.title) ? ' title="' + esc(o.title) + '"' : '';
    const dbm = (!isPair && o.disabled && o.title) ? ' data-backend-missing="' + esc(o.title) + '"' : '';
    const attrs = (attrsByValue && attrsByValue[value]) || {};
    const data = Object.keys(attrs).filter(function (k) {
      return attrs[k] !== null && attrs[k] !== undefined && attrs[k] !== '';
    }).map(function (k) { return ' data-' + esc(k) + '="' + esc(String(attrs[k])) + '"'; }).join('');
    const sel = (String(value) === String(selectedValue)) ? ' selected' : '';
    return '<option value="' + esc(value) + '"' + sel + dis + tit + dbm + data + '>' + esc(label) + '</option>';
  }

  // `data-group-key` : l'identité STABLE du groupe (`g.key`), le libellé n'étant qu'un texte
  // affiché. C'est par elle qu'un JS d'app retrouve un groupe (ex. « Mes voix », où le
  // synthesizer insère la voix qu'on vient de cloner) — plus par un `id` écrit à la main.
  function groupHtml(g, inner) {
    const key = g.key ? ' data-group-key="' + esc(g.key) + '"' : '';
    return '<optgroup label="' + esc(g.group || '') + '"' + key + '>' + inner + '</optgroup>';
  }

  // Contenu d'un <select> : gère le PLAT et les GROUPES (optgroup).
  // Source des groupes : (1) resolver renvoyant [{group, key?, options, attributes?}] (dynamique,
  // ex. voix par utilisateur), ou (2) p.option_groups statique [[libellé,[[v,l]]]].
  function selectInnerHtml(p, v, resolver) {
    function optEl(o) { return optionHtml(o, null, v); }
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
        return groupHtml(g, (g.options || []).map(function (o) {
          return optionHtml(o, g.attributes, v);
        }).join(''));
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
  // Une valeur en LISTE (2026-10-18) veut dire « l'une de » : la nature encore inconnue de ce que
  // recevra un nœud du Studio (image OU vidéo). Elle s'écrit jointe par « | », marquée
  // `data-any-of` : les conditions la relisent en liste (`met`), le jumeau serveur aussi
  // (`param_schema._show_if_met`).
  registerRenderer('hidden', function (p, api) {
    const v = api.value;
    const many = Array.isArray(v);
    return '<input type="hidden" id="' + api.id + '" ' + api.idAttr +
      (many ? ' data-any-of="1"' : '') +
      ' value="' + esc(many ? v.join('|') : (v != null ? v : '')) + '">';
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

  // ── Sources d'options ADOSSÉES À LA MÉDIATHÈQUE (2026-09-30) ─────────────────────────────
  // Un select dont les options SONT des assets de la médiathèque (les voix : `sa_`/`ua_`) reçoit,
  // d'office, un bouton qui ouvre la fenêtre commune (`MediaPicker`) sur SA nature : écouter,
  // AJOUTER (fichier ou micro) puis choisir, sans quitter l'app. Déclaré ICI par source, jamais
  // par app : tout champ `options_source: 'voices'` — volet et modale du synthesizer, modale de
  // l'avatarizer, nœud du Studio — l'a sans une ligne de plus. `optionFor(asset)` traduit l'asset
  // choisi en option du champ (`{value, group, groupLabel, label}`).
  var LIBRARY_SOURCES = {
    voices: { nature: 'voice', category: 'audio',
              optionFor: function (a) {
                return global.WamaModelCaps && WamaModelCaps.voiceOptionFor
                  ? WamaModelCaps.voiceOptionFor(a) : null;
              } },
  };

  registerRenderer('select', function (p, api) {
    const lib = p.options_source && LIBRARY_SOURCES[p.options_source];
    const select = '<select class="form-select form-select-sm" id="' + api.id + '" ' + api.idAttr +
      (lib ? ' data-library-source="' + esc(p.options_source) + '"' : '') + '>' +
      api.selectOptionsHtml(p) + '</select>';
    if (!lib) return select;
    return '<div class="input-group input-group-sm">' + select +
      '<button type="button" class="btn btn-outline-secondary" data-library-pick="' + api.id + '"' +
      ' title="Médiathèque : écouter, ajouter (fichier ou micro), choisir">' +
      '<i class="fas fa-photo-video"></i></button></div>';
  }, { modelHelp: true, optionSources: true });

  // ── GESTE ou REMPLISSAGE ? (2026-10-12) ───────────────────────────────────────────────────
  // Le moteur émet lui-même des `change` : à chaque recharge des options d'un select (pour que
  // l'appariement et les filtres se rejouent), et quand une fenêtre (médiathèque) pose une valeur
  // CHOISIE par l'utilisateur. Un consommateur qui ENREGISTRE ce qu'on règle — le graphe du
  // Studio, et son historique d'annulation — doit distinguer les deux : un remplissage n'est pas
  // une décision, un choix dans la médiathèque en est une, alors que ni l'un ni l'autre n'est un
  // évènement « de confiance » du navigateur. Les émissions qui portent un choix sont marquées
  // (`gestureEvent`) ; `isGesture(e)` répond pour tous les cas.
  function gestureEvent(type) {
    const e = new Event(type, { bubbles: true });
    e.wamaGesture = true;
    return e;
  }

  function isGesture(e) {
    return !!(e && (e.isTrusted || e.wamaGesture));
  }

  // Pose l'option (l'insère dans son groupe si le select ne la connaît pas encore — une voix
  // qu'on vient d'ajouter), la choisit, et le DIT (`change`) : appariement, grisage des moteurs
  // et puce de la voix clonée écoutent ce select comme s'il avait été choisi à la main.
  function _selectLibraryOption(select, o) {
    let opt = Array.prototype.find.call(select.options, function (x) { return x.value === o.value; });
    if (!opt) {
      let group = select.querySelector('optgroup[data-group-key="' + o.group + '"]');
      if (!group) {
        group = document.createElement('optgroup');
        group.label = o.groupLabel || o.group;
        group.setAttribute('data-group-key', o.group);
        select.appendChild(group);
      }
      opt = document.createElement('option');
      opt.value = o.value;
      opt.textContent = o.label;
      if (o.language) opt.setAttribute('data-language', o.language);
      group.appendChild(opt);
      // Les options ont changé : le dire comme la recharge commune le dit — les filtres de
      // capacité se rejouent (une voix clonée ne reste pas offerte sous un moteur qui ne clone pas).
      select.dispatchEvent(new CustomEvent('wama:options-filled', { bubbles: true }));
    }
    select.value = o.value;
    select.dispatchEvent(gestureEvent('change'));   // l'utilisateur l'a CHOISIE dans la fenêtre
  }

  // UN écouteur délégué pour toutes les surfaces (volet, modales rendues à la volée). Gardé : une
  // double inclusion du fichier ouvrirait deux fenêtres par clic (bug déjà vécu, `base.html`).
  if (!global.__wamaLibraryPickBound) document.addEventListener('click', function (e) {
    const btn = e.target.closest && e.target.closest('[data-library-pick]');
    if (!btn) return;
    const select = document.getElementById(btn.getAttribute('data-library-pick'));
    const lib = select && LIBRARY_SOURCES[select.getAttribute('data-library-source')];
    if (!lib || !global.MediaPicker) return;
    MediaPicker.open({
      type: lib.category, prefer: lib.nature, only: true, sources: 'all',
      onPick: function (asset) {
        const o = lib.optionFor(asset);
        if (o) _selectLibraryOption(select, o);
      },
    });
  });
  global.__wamaLibraryPickBound = true;

  registerRenderer('radio', function (p, api) {
    // name = groupage des radios (obligatoire) ; radio_name = pont vers le nom legacy si fourni
    // (string ou objet par contexte, comme dom_id).
    const id = api.id, idA = api.idAttr, v = api.value;
    // UN seul `name` par bouton (corrigé le 2026-09-27) : on posait `name="<id>"` PUIS l'attribut
    // d'identité, qui vaut `name="<param>"` dans une modale — le navigateur garde le PREMIER, et
    // un réglage radio d'une modale partait sous `wp-item-<param>`, que le serveur ne lit jamais
    // (mesuré sur le mode de l'anonymizer). Le nom historique déclaré (`radio_name`) prime ;
    // sinon celui de la modale ; au volet (`data-param`), l'id sert à grouper les boutons.
    const legacy = perCtx(p.radio_name, api.ctx);
    const posts = idA.indexOf('name=') === 0;
    const nameAttrs = legacy ? ('name="' + esc(legacy) + '"' + (posts ? '' : ' ' + idA))
                             : (posts ? idA : ('name="' + id + '" ' + idA));
    const rcls = p.inline ? 'form-check form-check-inline' : 'form-check';
    return api.options(p).map(function (o, i) {
      const checked = (String(o.value) === String(v)) ? 'checked' : '';
      const rid = id + '-' + i;
      return '<div class="' + rcls + '">' +
        '<input class="form-check-input" type="radio" ' + nameAttrs + ' id="' + rid + '"' +
        ' value="' + esc(o.value) + '" ' + checked + '>' +
        '<label class="form-check-label" for="' + rid + '">' + esc(o.label) + '</label></div>';
    }).join('');
  }, { labelIsBlock: true });

  registerRenderer('textarea', function (p, api) {
    return '<textarea class="form-control form-control-sm" id="' + api.id + '" ' + api.idAttr +
      ' rows="2">' + esc(api.value) + '</textarea>';
  });

  // L'UNITÉ déclarée se lit à côté de la valeur (2026-10-12) : un champ nombre la taisait — seul
  // le curseur l'affichait —, et un réglage de fonction en mètres ou en secondes perdait la
  // moitié de son sens en passant de la déclaration au formulaire. `step: 'any'` = décimal libre.
  registerRenderer('number', function (p, api) {
    const attrs = [p.min != null ? 'min="' + esc(p.min) + '"' : '',
                   p.max != null ? 'max="' + esc(p.max) + '"' : '',
                   p.step != null ? 'step="' + esc(p.step) + '"' : ''].join(' ');
    const input = '<input type="number" class="form-control form-control-sm" id="' + api.id + '" ' +
      api.idAttr + ' value="' + esc(api.value) + '" ' + attrs + '>';
    if (!p.unit) return input;
    return '<div class="input-group input-group-sm">' + input +
      '<span class="input-group-text">' + esc(p.unit) + '</span></div>';
  });

  // ── Désigner un média de la MÉDIATHÈQUE (2026-10-12, renderer commun) ─────────────────────
  // Un champ dont la valeur est le CHEMIN d'un asset (relatif à MEDIA_ROOT) : la valeur vit dans
  // un champ caché que `read()`/`apply()` voient comme tout champ ; un bouton ouvre la fenêtre
  // commune (`MediaPicker`) en DÉSIGNATION (`onPick` : l'asset est pointé, jamais recopié —
  // `MEDIA_STORAGE_TIERING §8.6` D10). Il n'existait que dans l'inspecteur du Studio, écrit à la
  // main et téléchargeant le fichier choisi pour n'en garder que l'URL : toute surface l'a
  // désormais, sans une ligne de plus.
  function _mediaShown(path) {
    return path ? String(path).split('/').pop() : '';
  }

  registerRenderer('media_picker', function (p, api) {
    const v = api.value || '';
    return '<input type="hidden" id="' + api.id + '" ' + api.idAttr + ' value="' + esc(v) + '">' +
      '<button type="button" class="btn btn-sm btn-outline-info w-100 text-truncate"' +
      ' data-media-pick="' + api.id + '" title="Médiathèque : choisir un média">' +
      '<i class="fas fa-photo-film me-1"></i><span class="wama-media-pick-name">' +
      esc(_mediaShown(v) || 'Choisir dans la médiathèque…') + '</span></button>';
  }, { labelIsBlock: true });

  if (!global.__wamaMediaPickBound) document.addEventListener('click', function (e) {
    const btn = e.target.closest && e.target.closest('[data-media-pick]');
    if (!btn) return;
    const field = document.getElementById(btn.getAttribute('data-media-pick'));
    if (!field || !global.MediaPicker) return;
    MediaPicker.open({
      type: 'all',
      onPick: function (asset) {
        if (!asset || !asset.path) return;
        field.value = asset.path;
        const name = btn.querySelector('.wama-media-pick-name');
        if (name) name.textContent = asset.name || _mediaShown(asset.path);
        field.dispatchEvent(gestureEvent('change'));
      },
    });
  });
  global.__wamaMediaPickBound = true;

  /** Libellé d'une VALEUR de réglage : le FORMAT déclaré (`display_format` : « duration » →
   *  « 3:30 », « size » → « 3,8 Go », formateurs communs de `WamaApp`), sinon la valeur suivie
   *  de son unité — l'affichage d'avant, inchangé pour tout réglage qui ne déclare rien. */
  function valueLabel(value, fmt, unit) {
    var A = global.WamaApp;
    if (fmt === 'duration' && A && A.formatDuration) return A.formatDuration(value);
    if (fmt === 'size' && A && A.formatSize) return A.formatSize(value);
    return String(value) + (unit || '');
  }

  registerRenderer('range', function (p, api) {
    const id = api.id, idA = api.idAttr, v = api.value;
    const rattrs = [p.min != null ? 'min="' + p.min + '"' : '',
                    p.max != null ? 'max="' + p.max + '"' : '',
                    p.step != null ? 'step="' + p.step + '"' : ''].join(' ');
    // Valeur courante à droite + bornes SOUS le slider — libellés FORMATÉS : min_label/max_label
    // déclarés priment (P2-bis), sinon le format déclaré (`display_format`), sinon valeur + unité.
    const unit = p.unit || '', fmt = p.display_format || '';
    return '<div class="wama-range">' +
      '<div class="d-flex align-items-center gap-2">' +
      '<input type="range" class="form-range" id="' + id + '" ' + idA + ' value="' + esc(v) + '" ' + rattrs +
      ' data-unit="' + esc(unit) + '" data-display-format="' + esc(fmt) + '"' +
      ' oninput="this.parentNode.querySelector(\'.wama-range-val\').textContent=' +
      'WamaParams.valueLabel(this.value,this.dataset.displayFormat,this.dataset.unit)">' +
      '<span class="wama-range-val small text-muted">' + esc(valueLabel(v, fmt, unit)) + '</span></div>' +
      ((p.min != null || p.max != null || p.min_label || p.max_label)
        ? '<div class="d-flex justify-content-between small text-muted" style="margin-top:-4px;opacity:.7">' +
          '<span>' + esc(p.min_label || (p.min != null ? valueLabel(p.min, fmt, unit) : '')) + '</span>' +
          '<span>' + esc(p.max_label || (p.max != null ? valueLabel(p.max, fmt, unit) : '')) + '</span></div>'
        : '') +
      '</div>';
  });

  // ── Curseur de QUALITÉ — échelle CONTINUE 0-100 (décision Fabien 02/09) ──────────────────
  // « L'intention n'est pas un branchement, c'est un POIDS dans le score » : la valeur
  // 0-100 voyage telle quelle jusqu'au sélecteur (les 3 politiques discrètes de la 1ʳᵉ
  // implémentation ne désignaient que 3 candidats sur N). Les positions nommées deviennent
  // des GRADUATIONS (Rapide 15 · Équilibré 50 · Qualité 85 — QUALITY_PRESETS serveur).
  // Tricolore par ZONE (tiers) : vert=léger/rapide · orange=équilibré · rouge=qualité (au
  // seuil serveur, l'offload ou l'attente de ressources est assumé — même rouge/orange que
  // les états de card). `!important` sur le libellé : les thèmes d'app posent la couleur
  // des small en !important (mesuré au smoke — sans lui le tricolore ne gagne jamais).
  // Le partial serveur `common/_intent_slider.html` (volets maison) rend ce MÊME markup :
  // la liaison ci-dessous est DÉLÉGUÉE au document, elle couvre les deux origines.
  var INTENT_ZONES = [
    { max: 33, label: 'Rapide', color: '#28a745' },
    { max: 66, label: 'Équilibré', color: '#fd7e14' },
    { max: 100, label: 'Qualité', color: '#dc3545' },
  ];
  function intentZone(value) {
    var v = parseInt(value, 10);
    if (isNaN(v)) v = 50;
    for (var i = 0; i < INTENT_ZONES.length; i++) {
      if (v <= INTENT_ZONES[i].max) return INTENT_ZONES[i];
    }
    return INTENT_ZONES[2];
  }
  registerRenderer('intent', function (p, api) {
    var v = parseInt(api.value, 10);
    if (isNaN(v)) v = 50;
    v = Math.max(0, Math.min(100, v));
    var z = intentZone(v);
    // L'échelle est 0-100 PAR CONTRAT (les zones en dépendent) ; seul le PAS se déclare —
    // un moteur à paliers discrets (anonymizer : 5 réels) dit ainsi la vérité du curseur.
    var step = parseInt(p.step, 10) || 1;
    // Les graduations vivent SOUS LE CURSEUR, dans sa colonne (`wama-intent-track`) : posées
    // sous toute la ligne, elles s'étalaient aussi sous la valeur affichée à droite (2026-10-13).
    // La valeur s'aligne sur le CURSEUR (haut de ligne, hauteur d'un `.form-range`), pas sur le
    // milieu de la colonne curseur + graduations.
    return '<div class="wama-intent">' +
      '<div class="d-flex align-items-start gap-2">' +
      '<div class="wama-intent-track flex-grow-1" style="min-width:0">' +
      '<input type="range" class="form-range wama-intent-slider" min="0" max="100" step="' + step + '"' +
      ' id="' + api.id + '" ' + api.idAttr + ' value="' + v + '"' +
      ' style="accent-color:' + z.color + '"' +
      ' aria-label="' + esc(p.label || 'Rapide ou qualité') + '">' +
      '<div class="d-flex justify-content-between small text-muted" style="margin-top:-4px;opacity:.7">' +
      '<span>Rapide</span><span>Équilibré</span><span>Qualité</span></div></div>' +
      '<span class="wama-intent-val small fw-bold text-nowrap" style="line-height:1.5rem;color:' +
      z.color + ' !important">' + v + ' · ' + z.label + '</span></div></div>';
  });
  document.addEventListener('input', function (e) {
    var slider = e.target;
    if (!slider.classList || !slider.classList.contains('wama-intent-slider')) return;
    var wrap = slider.closest('.wama-intent');
    if (!wrap) return;
    var z = intentZone(slider.value);
    slider.style.accentColor = z.color;
    var lab = wrap.querySelector('.wama-intent-val');
    if (lab) {
      lab.textContent = slider.value + ' · ' + z.label;
      lab.style.setProperty('color', z.color, 'important');
    }
    // Le slider porte lui-même id/name : read()/apply() le voient comme tout champ, et le
    // 'change' NATIF (au relâchement) déclenche la prévision — pas un fetch par pixel.
  });
  // Resynchronise la SURFACE d'un curseur depuis sa valeur (après apply()).
  function _syncIntentSliders(container) {
    (container || document).querySelectorAll('.wama-intent .wama-intent-slider').forEach(function (slider) {
      var z = intentZone(slider.value);
      slider.style.accentColor = z.color;
      var lab = slider.closest('.wama-intent').querySelector('.wama-intent-val');
      if (lab) {
        lab.textContent = slider.value + ' · ' + z.label;
        lab.style.setProperty('color', z.color, 'important');
      }
    });
  }

  // Repli : type absent du registry → champ texte (comportement historique du `else` final).
  registerRenderer('text', function (p, api) {
    return '<input type="text" class="form-control form-control-sm" id="' + api.id + '" ' +
      api.idAttr + ' value="' + esc(api.value) + '">';
  });

  // Date et heure LOCALES (2026-09-28, programmation d'une card — `scheduled_actions.
  // schedule_params`). La valeur lue est celle du navigateur (`AAAA-MM-JJTHH:MM`, sans fuseau) :
  // le serveur la lit à l'heure de l'instance, comme le reste de l'interface.
  registerRenderer('datetime', function (p, api) {
    return '<input type="datetime-local" class="form-control form-control-sm w-auto" id="' +
      api.id + '" ' + api.idAttr + ' value="' + esc(api.value || '') + '">';
  });

  // Une date SEULE (2026-10-21, la date du document du transcriber) — `AAAA-MM-JJ`, vide = pas de
  // date (le serveur l'efface, `param_schema._coerce_date`).
  registerRenderer('date', function (p, api) {
    return '<input type="date" class="form-control form-control-sm w-auto" id="' +
      api.id + '" ' + api.idAttr + ' value="' + esc(api.value || '') + '">';
  });

  // Une CORRESPONDANCE `{clé: texte}` (2026-10-21, les noms des intervenants du transcriber) : une
  // ligne par clé de la VALEUR, son texte éditable. La valeur lue est le JSON de l'objet (champ
  // caché qui porte le nom), que le serveur assainit (`param_schema._coerce_mapping`). Les clés
  // viennent de qui rend : une brique qui les connaît (les locuteurs des segments) les pose dans
  // la valeur, vides si besoin.
  registerRenderer('mapping', function (p, api) {
    var v = api.value;
    if (typeof v === 'string') { try { v = JSON.parse(v || '{}'); } catch (e) { v = {}; } }
    v = (v && typeof v === 'object' && !Array.isArray(v)) ? v : {};
    var rows = Object.keys(v).map(function (k) {
      return '<div class="wama-param-mapping-row"><span class="wama-param-mapping-key">' + esc(k) + '</span>' +
        '<input type="text" class="form-control form-control-sm" data-key="' + esc(k) +
        '" value="' + esc(v[k] == null ? '' : v[k]) + '"></div>';
    }).join('');
    return '<div class="wama-param-mapping" data-mapping-for="' + api.id + '">' + rows + '</div>' +
      '<input type="hidden" id="' + api.id + '" ' + api.idAttr + ' value="' + esc(JSON.stringify(v)) + '">';
  });

  /** Une ligne de correspondance éditée réécrit le JSON du champ caché que `read()` lit. */
  function _bindMapping(container) {
    container.querySelectorAll('[data-mapping-for]').forEach(function (box) {
      var hidden = document.getElementById(box.getAttribute('data-mapping-for'));
      if (!hidden || box._wpMapping) return;
      box._wpMapping = true;
      box.addEventListener('input', function () {
        var out = {};
        box.querySelectorAll('input[data-key]').forEach(function (inp) { out[inp.getAttribute('data-key')] = inp.value; });
        hidden.value = JSON.stringify(out);
      });
    });
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
    // Resolver PAR DÉFAUT = le registre commun des sources de PAGE (2026-09-01). Avant, une
    // app devait passer sa propre fonction pour que `options_source` résolve quoi que ce soit
    // — d'où les TROIS resolvers `formats` recopiés dans le converter (modale d'item, modale
    // de lot, volet), tous adossés à la même table que `PAGE_OPTION_SOURCES`. Le moteur sait
    // désormais résoudre seul ce que le SCHÉMA déclare ; une app ne passe un resolver que
    // pour une source qui lui est PROPRE. `resolvePageOptions` rend null hors de sa famille,
    // et `optionsFor`/`selectInnerHtml` continuent alors la chaîne (option_groups, choices).
    const resolver = opts.optionsResolver
      || function (p) { return resolvePageOptions(p, values, ctx); };

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
    _bindMapping(container);
    _bindModelHelp(container, schema, ctx);
    _bindCapFrom(container, schema, ctx);
    _bindDefaultFrom(container, schema, ctx);
    _bindOptionSources(container, schema, ctx, null, values);
    _avertirSourcesNonResolues(container, params, ctx);
  }

  // Garde « clé qui ne résout nulle part » — PORTÉE AU COMMUN le 2026-09-01. Elle n'existait
  // que dans le resolver ÉMIS par le générateur d'apps ; les 10 apps écrites à la main n'en
  // avaient aucune, et un select vide n'y disait pas s'il l'était par absence d'options ou
  // par défaut de câblage. On ne signale QUE le cas insoluble : ni resolver, ni registre de
  // page, ni statique, ni endpoint async (ceux-là se peuplent après ce point).
  function _avertirSourcesNonResolues(container, params, ctx) {
    params.forEach(function (p) {
      if (!p.options_source || OPTION_SOURCES[p.options_source]) return;
      const sel = container.querySelector('[data-param="' + p.name + '"], [name="' + p.name + '"]');
      if (!sel || sel.tagName !== 'SELECT' || sel.options.length) return;
      console.warn('[WamaParams] options_source « ' + p.options_source + ' » (' + p.name +
                   ', contexte ' + ctx + ') : aucune source ne la résout — la déclarer au ' +
                   'registre commun PAGE_OPTION_SOURCES, ou fournir un optionsResolver.');
    });
  }

  // Sources d'options ASYNC centralisées (manifeste) : options_source → endpoint renvoyant {groups}.
  // Ex. 'voices' → /common/api/voices/ (peuple les optgroups voix sans markup serveur par app).
  // Surchageable via window.WAMA_OPTION_SOURCES. Si la clé n'est pas connue ici, l'app fournit un
  // optionsResolver synchrone à la place (rétro-compatible).
  // `catalog` (2026-08-31, route F4b) : les options d'un select de MODÈLE viennent du
  // CATALOGUE, plus d'une liste écrite dans l'app. Le domaine se déclare au schéma via
  // `options_query` (cf. ci-dessous) — sans quoi une clé, qui ne porte qu'une URL fixe,
  // ne saurait pas DE QUOI parler.
  // `avatar_gallery` (2026-10-12) : les avatars que l'utilisateur peut NOMMER — la liste même que
  // résout `designate_named_avatar` (`avatarizer/system_assets.py`). Elle n'était servie que par la
  // vue du Studio, en option de page : la clé était déclarée sans être résolue nulle part ailleurs.
  var OPTION_SOURCES = global.WAMA_OPTION_SOURCES || {
    voices: '/common/api/voices/',
    catalog: '/model-manager/api/models/options/',
    avatar_gallery: '/avatarizer/api/avatar-gallery/',
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

  // Valeur d'un champ VOISIN dans le même conteneur, quel que soit son rendu : `name` (modale),
  // `data-param` (volet), radios (la cochée), case à cocher. Sert `options_mode` ci-dessous.
  function _siblingValue(root, name) {
    var els = (root || document).querySelectorAll('[name="' + name + '"], [data-param="' + name + '"]');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (el.type === 'radio') { if (el.checked) return el.value; continue; }
      return el.type === 'checkbox' ? (el.checked ? 'true' : 'false') : el.value;
    }
    return '';
  }

  // `only` (optionnel) : prédicat de filtrage — permet à un appelant EXTERNE (volet via
  // WamaInspector.initFromSchema) de ne lier que certaines sources. Ce qu'il sert : ne pas
  // lier DEUX FOIS un champ que l'app a déjà rendu elle-même (le champ de voix du volet
  // synthesizer, généré et donc lié par son propre `render` — une seconde liaison
  // refetcherait et reconstruirait le select par-dessus).
  // ⚠ Jusqu'au 2026-09-23 cette ligne justifiait le filtre autrement : « les voix du volet
  // restent rendues SERVEUR, les remplacer casserait le clonage ». C'était la phrase du
  // schéma synthesizer, recopiée — elle est fausse depuis que ce volet génère son champ.
  function _bindOptionSources(container, schema, ctx, only, values) {
    (schema || []).forEach(function (p) {
      if (only && !only(p)) return;
      if (!typeSupports(p.type, 'optionSources') || !p.options_source) return;
      if (p.contexts && p.contexts.indexOf(ctx) === -1) return;
      var url = OPTION_SOURCES[p.options_source];
      if (!url) return;   // pas d'endpoint connu → l'app gère via optionsResolver (rendu synchrone)
      // La querystring fait partie de l'URL — donc aussi de la CLÉ DE CACHE : deux domaines
      // distincts sur la même page (ex. un select TTS et un select ASR) ne doivent pas se
      // servir mutuellement leur liste.
      url += _optionQuery(p);
      // `options_auto` (schéma, route F4b) : « auto » en 1ʳᵉ option + PRÉVISION du modèle
      // retenu. Hors de `options_query` À DESSEIN : c'est un drapeau d'UI, pas une borne de
      // domaine — les consommateurs serveur du domaine (chips de card…) ne doivent pas le voir.
      // `options_auto: "group"` (2026-10-01) : un « auto:<tâche> » par groupe de tâche.
      // `options_auto: "silent"` (2026-10-03) : « auto » SANS prévision — le tirage dépend des
      // entrées de chaque élément, la prévision ne pourrait pas dire vrai (avatarizer).
      if (p.options_auto) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'auto=' +
        (p.options_auto === 'group' ? 'group' : (p.options_auto === 'silent' ? 'silent' : '1'));
      // `options_cloud` (2026-09-16) : même nature que `options_auto` — un drapeau d'UI, pas une
      // borne de domaine. Le serveur ajoute alors les modèles DISTANTS que les clés de CET
      // utilisateur ouvrent, selon son niveau cloud.
      if (p.options_cloud) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'cloud=1';
      // `options_resolution` (2026-10-01) : les affinages du TIRAGE « auto » déclarés au schéma
      // (priorité, entrées fournies) — le lancement les lit au même schéma ; sans eux la
      // PRÉVISION annonçait un autre modèle que celui que le lancement retient.
      if (p.options_auto && p.options_resolution) {
        Object.keys(p.options_resolution).sort().forEach(function (k) {
          if (k === 'needs') return;   // des CHAMPS, dont la valeur est lue plus bas (`needsQuery`)
          var v = p.options_resolution[k];
          if (v && v.length) url += (url.indexOf('?') >= 0 ? '&' : '?') +
            encodeURIComponent(k) + '=' + encodeURIComponent([].concat(v).join(','));
        });
      }
      // `options_abilities` (2026-09-17) : le libellé porte les capacités déclarées du modèle.
      if (p.options_abilities) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'abilities=1';
      // `options_group` (2026-09-27) : drapeau d'UI lui aussi — les options arrivent groupées.
      if (p.options_group) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'group=' + encodeURIComponent(p.options_group);
      // Curseur d'INTENTION du même contexte : la prévision arbitre comme le tirage
      // arbitrera. L'intention entre dans l'URL — donc dans la clé de cache — et son
      // changement RAFRAÎCHIT la prévision (sans re-remplir le select : seule la note bouge).
      var intentEl = null;
      if (p.options_auto) {
        var pi = (schema || []).filter(function (x) { return x.type === 'intent'; })[0];
        if (pi && (!pi.contexts || pi.contexts.indexOf(ctx) !== -1)) {
          intentEl = document.getElementById(perCtx(pi.dom_id, ctx) || ('wp-' + ctx + '-' + pi.name));
        }
      }
      var baseUrl = url;   // figé AVANT l'ajout d'intention (la fermeture ci-dessous en dépend)
      // `options_mode` (2026-09-27) : la liste est BORNÉE PAR LE MODE de l'élément — la valeur du
      // champ déclaré (`app_modes.mode_param`), lue dans le MÊME conteneur, part avec la requête ;
      // le serveur en dérive ce que le mode impose au modèle. Sa valeur entre dans l'URL, donc
      // dans la clé de cache : deux modes ne se servent jamais la liste l'un de l'autre.
      var om = p.options_mode;
      var root = container || document;
      var modeQuery = function () {
        if (!om || !om.field) return '';
        var v = _siblingValue(root, om.field);
        return v ? ((baseUrl.indexOf('?') >= 0 ? '&' : '?') + 'app=' + encodeURIComponent(om.app) +
                    '&domain=' + encodeURIComponent(om.domain) + '&mode=' + encodeURIComponent(v)) : '';
      };
      // `options_resolution.needs` (2026-10-14) : le BESOIN de l'élément, {capacité: champ}. La
      // valeur du champ (enhancer : le facteur ×2/×4) part avec la requête — le lancement lit le
      // même champ sur l'élément ; sans elle la prévision se taisait (liste multi-tâches) et en
      // liste simple aurait annoncé un ×2 pour un élément ×4. Elle entre dans l'URL, donc dans la
      // clé de cache, et son changement rafraîchit la prévision comme celui de l'intention.
      var needEls = [];
      if (p.options_auto && p.options_resolution && p.options_resolution.needs) {
        Object.keys(p.options_resolution.needs).sort().forEach(function (cap) {
          var field = p.options_resolution.needs[cap];
          var pf = (schema || []).filter(function (x) { return x.name === field; })[0];
          needEls.push({ cap: cap, field: field,
                         el: pf ? document.getElementById(perCtx(pf.dom_id, ctx) || ('wp-' + ctx + '-' + field)) : null });
        });
      }
      var needsQuery = function () {
        var pairs = needEls.map(function (n) {
          var v = n.el ? n.el.value : _siblingValue(root, n.field);
          return v ? n.cap + ':' + v : '';
        }).filter(Boolean);
        return pairs.length ? 'needs=' + encodeURIComponent(pairs.join(',')) : '';
      };
      var urlWithIntent = function () {
        var u = baseUrl + modeQuery();
        var nq = needsQuery();
        if (nq) u += (u.indexOf('?') >= 0 ? '&' : '?') + nq;
        return u + (intentEl && intentEl.value
          ? (u.indexOf('?') >= 0 ? '&' : '?') + 'quality_intent=' + encodeURIComponent(intentEl.value) : '');
      };
      url = urlWithIntent();
      var sid = perCtx(p.dom_id, ctx) || ('wp-' + ctx + '-' + p.name);
      var sel = document.getElementById(sid);
      if (!sel) return;
      // UNE liaison par select (2026-10-11). Un champ de volet GÉNÉRÉ est lié par son `render`,
      // puis l'inspecteur (`initFromSchema`) relie les selects `catalog` du volet — pensé pour les
      // volets rendus serveur. La seconde liaison relançait la requête : sa réponse, seule
      // retenue (`_wpOptionsSeq`), remplissait SANS la valeur demandée au rendu (`wanted`) — le
      // select retombait sur « auto ». Un `render` crée des éléments neufs : rien n'est sauté
      // à tort.
      if (sel._wpOptionsBound) return;
      sel._wpOptionsBound = true;
      // The value ASKED FOR at render (2026-09-24). When the options arrive asynchronously, the
      // asked value is usually not an option yet at render time: the select falls back to its
      // first option, and restoring only the CURRENT value (below) then lost the stored one.
      // Measured on the avatarizer's generated item modal: stored 'synthesizer:coqui-xtts',
      // shown 'auto' — saving would have overwritten the chosen engine, silently. The static
      // modals it replaced never showed it: they were filled at page load, valued at open.
      // Applied on the FIRST fill only; afterwards the user's own choice prevails.
      var wanted = (values && p.name in values && values[p.name] !== null
                    && values[p.name] !== undefined && values[p.name] !== '')
        ? String(values[p.name]) : null;
      var fill = function (d) {
        var cur = sel.value;
        // Même rendu d'option que le chemin synchrone (`optionHtml`/`groupHtml`, ci-dessus).
        sel.innerHTML = (d.groups || []).map(function (g) {
          var opts = (g.options || []).map(function (o) { return optionHtml(o, g.attributes); }).join('');
          return g.group ? groupHtml(g, opts) : opts;
        }).join('');
        if (wanted !== null && Array.prototype.some.call(sel.options, function (o) { return o.value === wanted; })) {
          sel.value = wanted;
        } else if (cur) {
          sel.value = cur;
        }
        // Valeur disparue de la nouvelle liste (un modèle d'un autre mode) : la PREMIÈRE option,
        // jamais un select sans sélection — sa lecture rendrait '' (mesuré au smoke du 27/09).
        if (sel.selectedIndex < 0 && sel.options.length) sel.selectedIndex = 0;
        wanted = null;
        _bindAutoPreview(sel, d.auto_preview);
        // « Options prêtes » (2026-09-22) : les options de CE select viennent d'être REMPLACÉES.
        // Le `change` ci-dessous ne suffisait pas : les filtres de WamaModelCaps ne se rejouent
        // que sur un changement du select de MODÈLE — une recharge des VOIX qui arrivait après
        // eux effaçait en silence les voix masquées et les ⚠ de langue qu'ils avaient posés.
        // Ceux qui tiennent un état sur ces options (filtres, miroirs d'app) écoutent CE signal.
        sel.dispatchEvent(new CustomEvent('wama:options-filled', { bubbles: true }));
        sel.dispatchEvent(new Event('change', { bubbles: true }));   // re-déclenche WamaInputMatch/conditionnel
      };
      // Changement d'intention ou d'un BESOIN → seule la PRÉVISION se rafraîchit (les options du
      // domaine n'en dépendent pas — re-remplir le select perdrait la sélection).
      var refreshPreview = function () {
        var u = urlWithIntent();
        var use = function (d) { _bindAutoPreview(sel, (d || {}).auto_preview); };
        if (_optionSourceCache[u]) { use(_optionSourceCache[u]); return; }
        fetch(u, { credentials: 'same-origin' })
          .then(function (r) { return r.json(); })
          .then(function (d) { _optionSourceCache[u] = d || {}; use(_optionSourceCache[u]); })
          .catch(function () {});
      };
      if (intentEl && !intentEl._wpIntentPreviewBound) {
        intentEl._wpIntentPreviewBound = true;
        intentEl.addEventListener('change', refreshPreview);
      }
      needEls.forEach(function (n) {
        if (n.el && !n.el._wpNeedPreviewBound) {
          n.el._wpNeedPreviewBound = true;
          n.el.addEventListener('change', refreshPreview);
        }
      });
      // La DERNIÈRE demande seule remplit le select : la première part avant que le mode ne
      // soit connu, et sa réponse peut arriver APRÈS celle du mode — elle remettait alors la
      // liste non bornée (mesuré au smoke du 2026-09-27 : SAM3 proposé en mode « Classes »).
      var load = function (u) {
        var seq = sel._wpOptionsSeq = (sel._wpOptionsSeq || 0) + 1;
        if (_optionSourceCache[u]) { fill(_optionSourceCache[u]); return; }
        fetch(u, { credentials: 'same-origin' })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            _optionSourceCache[u] = d || {};
            if (sel._wpOptionsSeq === seq) fill(_optionSourceCache[u]);
          })
          .catch(function () {});
      };
      // Changement de MODE → la LISTE change (contrairement à l'intention) : on re-remplit. La
      // sélection est gardée si le modèle existe dans le nouveau mode, sinon le select revient
      // à sa première option (« auto » quand le schéma la sert).
      if (om && om.field && !sel._wpModeBound) {
        sel._wpModeBound = true;
        root.addEventListener('change', function (e) {
          var tg = e.target;
          if (!tg || !tg.matches || !tg.matches('[name="' + om.field + '"], [data-param="' + om.field + '"]')) return;
          load(urlWithIntent());
        });
      }
      load(url);
    });
  }

  // ── Prévision du choix « auto » (route F4b, décision Fabien 2026-09-01) ─────────────────
  // Sous le select, quand la valeur est « auto » : le modèle qui SERAIT retenu maintenant.
  // La prévision vient de l'endpoint (même chemin que le tirage réel — VRAM libre, résidence) ;
  // c'est une photo au rendu, le lancement réévalue — et le dit dans la console de l'item.
  function _bindAutoPreview(sel, preview) {
    var note = sel.parentNode ? sel.parentNode.querySelector('.wp-auto-preview') : null;
    if (!preview || !preview.name) { if (note) note.hidden = true; return; }
    if (!note) {
      note = document.createElement('div');
      note.className = 'wp-auto-preview form-text text-muted small';
      sel.insertAdjacentElement('afterend', note);
    }
    note.textContent = _autoPreviewText(preview);
    var refresh = function () { note.hidden = (sel.value !== 'auto'); };
    if (!sel._wpAutoPreviewBound) {
      sel._wpAutoPreviewBound = true;
      sel.addEventListener('change', refresh);
    }
    refresh();
  }

  // Texte de la prévision. La PROVENANCE y figure (2026-10-13, Fabien : « Prévu : qwen-3.8-27b »
  // ne disait pas que c'était ILaaS) — la phrase des intitulés de groupe du menu, calculée par le
  // serveur (`AIModel.origin_label`) : « WAMA local · Ollama », « Cloud souverain · ILaaS (ESR) ·
  // gratuit (quota) ». Un modèle distant n'a pas de VRAM locale : rien ne s'affiche à sa place.
  function _autoPreviewText(preview) {
    var vram = preview.vram_gb ? ' (' + preview.vram_gb + ' Go)' : '';
    var origin = preview.origin ? ' · ' + preview.origin : '';
    return 'Prévu : ' + preview.name + vram + origin + ' — réévalué au lancement';
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
    // resolver historique du converter (`converter.js`) : l'option vide puis « .PNG ».
    // L'option VIDE (2026-10-18) : « Automatique (selon l'entrée) » — le format de la nature,
    // résolu par le serveur (`format_router.output_format_for`) au dépôt, sur un nœud du Studio,
    // à l'« Envoyer vers » ; dans une modale de LOT elle reste « — inchangé — » (vide = ne pas
    // toucher, la règle de `read_settings_payload`).
    formats: function (values, p, ctx) {
      var table = global.WAMA_OUTPUT_FORMATS || {};
      var mt = (values || {}).media_type;
      // Une nature encore inconnue parmi plusieurs (liste, nœud du Studio) : leurs formats réunis.
      var natures = Array.isArray(mt) ? mt : null;
      var liste = natures ? [] : (table[mt] || []);
      if (natures) {
        natures.forEach(function (k) {
          (table[k] || []).forEach(function (f) { if (liste.indexOf(f) === -1) liste.push(f); });
        });
      } else if (!mt) {
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
      var empty = ctx === 'batch' ? '— inchangé —' : 'Automatique (selon l’entrée)';
      return [{ value: '', label: empty }].concat(liste.map(function (f) {
        return { value: f, label: '.' + String(f).toUpperCase() };
      }));
    },
  };

  // (param, valeurs, contexte) -> options plates, ou null si la clé n'appartient pas à cette
  // famille. Renvoyer null (et non []) est ce qui laisse l'appelant distinguer « pas ma famille »
  // de « ma famille, mais rien à proposer » — la distinction que le select vide effaçait.
  // `ctx` (2026-10-18) : la surface du rendu — la même valeur ne veut pas dire la même chose
  // partout (une modale de LOT lit « vide » comme « ne pas toucher »).
  function resolvePageOptions(p, values, ctx) {
    if (!p || !p.options_source) return null;
    var reg = global.WAMA_PAGE_OPTION_SOURCES || PAGE_OPTION_SOURCES;
    var f = reg[p.options_source];
    return f ? f(values || {}, p, ctx) : null;
  }

  // ── Réglages BORNÉS PAR LA CAPACITÉ DU MODÈLE choisi (`cap_from`, 2026-09-23) ─────────────
  // Demande de Fabien : « les paramètres modale/inspecteur tirent leurs infos des capacités des
  // modèles dans le registre ». Un param déclare `cap_from: {field, capability, extension?,
  // mode?, unit?, label?}` ; les capacités viennent du CATALOGUE (api/models/db/, champ
  // `capabilities`) — la même source que la tâche serveur lit, jamais une liste recopiée ici.
  //   • range (défaut) : zone NATIVE (bleue) jusqu'à la capacité. Au-delà : zone EXTRAPOLÉE
  //     (rouge) si le modèle déclare `extension`, sinon le curseur est BORNÉ à la capacité.
  //   • mode 'fixed'   : la capacité IMPOSE la valeur (cadence native) → champ verrouillé, dit.
  //   • mode 'note'    : la capacité est seulement RAPPELÉE sous le champ (résolution native).
  //   • mode 'reads'   : le champ est GRISÉ, raison dite, quand le modèle ne le lit pas —
  //     capacité liste (`params`) ou booléenne (`supports_*`) (2026-10-13).
  // Modèle « auto » ou sans la capacité → champ du schéma, intact (dégradation douce).
  var _capsBySource = {};
  // `query` (2026-09-29) : domaine d'un select peuplé du CATALOGUE (`_optionQuery` du param
  // modèle). Les capacités se lisent alors sur le MÊME lot que les options — sources confondues :
  // un modèle `huggingface:…` proposé à l'imager n'était jamais dans `?source=imager`.
  function _catalogCaps(source, query) {
    var cacheKey = source + '|' + (query || '');
    if (!_capsBySource[cacheKey]) {
      _capsBySource[cacheKey] = fetch('/model-manager/api/models/db/' +
                                      (query || ('?source=' + encodeURIComponent(source))))
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var out = {};
          (data.models || []).forEach(function (m) {
            var key = m.model_key || '';
            // Clé ENTIÈRE et id NU (même règle que WamaModelHelp) : un select du catalogue porte
            // la clé entière, un select d'app en liste propre l'id nu.
            out[key] = m.capabilities || {};
            if (key.indexOf(source + ':') === 0) out[key.slice(source.length + 1)] = out[key];
          });
          return out;
        })
        .catch(function () { return {}; });
    }
    return _capsBySource[cacheKey];
  }

  // Domaine CATALOGUE d'un param de modèle (sa querystring d'options), ou '' s'il n'est pas peuplé
  // du catalogue — l'aide et `cap_from` se lisent alors sur le MÊME lot que ses options.
  function _catalogDomain(p) {
    return (p && p.options_source === 'catalog') ? _optionQuery(p) : '';
  }

  function _fmtNum(v) {
    var n = Number(v);
    return (Math.round(n * 10) / 10).toString().replace('.', ',');
  }

  /** Valeur PROPOSÉE d'après une ENTRÉE de la card (`default_from`, 2026-10-04 — la durée du
   *  composer reprend celle de la chanson à reprendre). Le port déclaré est retrouvé par la card
   *  d'entrée elle-même (`WamaInputSlots.filePorts`, la brique de la card) : aucune app ne nomme
   *  son input. Au dépôt OU à la désignation (`designateInto` émet le même `change`), la propriété est
   *  lue (`WamaApp.mediaDuration`) puis posée — arrondie au pas, BORNÉE par le max du moment
   *  (celui que `cap_from` a posé pour le modèle choisi). Contexte : la surface de CRÉATION
   *  (`panel`, là où vit la card d'entrée) — une modale d'élément existant ne suit pas le fichier
   *  de la prochaine card. Un écouteur par input, qui relit ses cibles au moment du geste. */
  var DEFAULT_FROM_PROPERTIES = { duration: function (input) { return global.WamaApp.mediaDuration(input); } };

  function _proposedValue(target, raw) {
    var step = Number(target.step) || 1, min = Number(target.min), max = Number(target.max);
    var v = Math.round(raw / step) * step;
    if (isFinite(max) && target.max !== '') v = Math.min(v, max);
    if (isFinite(min) && target.min !== '') v = Math.max(v, min);
    return v;
  }

  function _bindDefaultFrom(container, schema, ctx) {
    (schema || []).forEach(function (p) {
      var df = p.default_from;
      if (!df || !df.port || !DEFAULT_FROM_PROPERTIES[df.property]) return;
      if ((df.contexts || ['panel']).indexOf(ctx) === -1) return;
      if (p.contexts && p.contexts.indexOf(ctx) === -1) return;
      var targetId = perCtx(p.dom_id, ctx) || ('wp-' + ctx + '-' + p.name);
      if (!container.querySelector('#' + CSS.escape(targetId))) return;
      // Les panes n'existent qu'avec la card, qui charge sa brique avant eux : sans elle, pas de port.
      var port = (global.WamaInputSlots ? global.WamaInputSlots.filePorts(document) : [])
        .filter(function (q) { return q.id === df.port; })[0];
      var input = port && document.getElementById(port.inputId);
      if (!input) return;                    // pas de card d'entrée portant ce port sur la page
      input._wpDefaultFrom = input._wpDefaultFrom || {};
      var already = Object.keys(input._wpDefaultFrom).length > 0;
      input._wpDefaultFrom[targetId] = df.property;
      if (already) return;
      input.addEventListener('change', function () {
        if (!global.WamaApp || !global.WamaApp.mediaDuration) return;
        Object.keys(input._wpDefaultFrom).forEach(function (id) {
          DEFAULT_FROM_PROPERTIES[input._wpDefaultFrom[id]](input).then(function (raw) {
            var target = document.getElementById(id);
            if (!target || !(Number(raw) > 0)) return;
            target.value = _proposedValue(target, Number(raw));
            target.dispatchEvent(new Event('input', { bubbles: true }));
            target.dispatchEvent(new Event('change', { bubbles: true }));
          });
        });
      });
    });
  }

  /** Libellé d'une CAPACITÉ (borne de modèle) : le format déclaré du réglage, sinon le nombre
   *  arrondi suivi de l'unité (l'affichage d'avant). */
  function _capLabel(cap, p, unit) {
    return p && p.display_format ? valueLabel(cap, p.display_format, unit) : _fmtNum(cap) + unit;
  }

  function _applyCap(el, note, row, p, cf, caps) {
    var cap = caps ? caps[cf.capability] : null;
    var unit = cf.unit || p.unit || '';
    var mode = cf.mode || 'range';
    note.textContent = '';
    note.classList.remove('is-extrapolated');
    if (row) row.classList.remove('is-extrapolated');
    if (mode === 'note') {
      if (cap) note.textContent = (cf.label || 'Natif :') + ' ' + cap + unit;
      return;
    }
    if (mode === 'reads') {
      // Le modèle choisi LIT-il ce réglage ? Une capacité LISTE (`params`, les réglages que le
      // moteur lit) répond par l'appartenance du nom ; une capacité BOOLÉENNE (`supports_*`) par
      // sa valeur. Inconnu (« auto », capacité non déclarée) : intact — on ne grise jamais sur
      // une absence d'information. Grisé, jamais caché (INPUT_MODEL_MATCHING) ; la valeur reste
      // celle de l'utilisateur, `read()` l'envoie toujours (2026-10-13).
      var unread = cap !== undefined && cap !== null &&
        (Array.isArray(cap) ? cap.indexOf(cf.param || p.name) === -1 : !cap);
      var why = cf.reason || 'Ce modèle ne tient pas compte de ce réglage.';
      el.disabled = unread;
      el.title = unread ? why : '';
      if (row) row.classList.toggle('opacity-50', unread);
      if (unread) note.textContent = why;
      return;
    }
    if (mode === 'fixed') {
      if (el.dataset.userValue === undefined) el.dataset.userValue = el.value;
      if (cap != null && cap !== '') {
        el.value = cap;
        el.disabled = true;
        note.textContent = (cf.label || 'Imposé par le modèle :') + ' ' + cap + unit;
      } else if (el.disabled) {
        el.disabled = false;
        el.value = el.dataset.userValue;
      }
      return;
    }
    // range
    var min = Number(p.min != null ? p.min : el.min || 0);
    var max = Number(p.max != null ? p.max : el.max || 100);
    el.max = max;
    el.classList.remove('wama-range-capped');
    el.style.removeProperty('--wama-cap-pct');
    if (!(Number(cap) > 0)) return;
    var ext = cf.extension && caps[cf.extension];
    if (!ext) {
      // Pas d'au-delà : le curseur S'ARRÊTE à la capacité (jamais une valeur qui serait réduite
      // en silence à l'exécution).
      var bound = Math.max(min, Math.min(max, Math.floor(Number(cap))));
      // Valeur lue AVANT de baisser `max` : un navigateur ramène de lui-même la valeur d'un
      // <input range> dans ses bornes, SANS événement — la comparaison faite après ne voyait
      // donc jamais de dépassement, et ni le nombre affiché ni les écouteurs de l'app
      // (estimation) n'étaient mis à jour (vu au navigateur le 2026-10-03, composer).
      var asked = Number(el.value);
      el.max = bound;
      if (asked > bound) {
        el.value = bound;
        el.dispatchEvent(new Event('input', { bubbles: true }));
      }
      note.textContent = 'Limite du modèle : ' + _capLabel(cap, p, unit);
      return;
    }
    var pct = Math.max(0, Math.min(100, (Number(cap) - min) / ((max - min) || 1) * 100));
    // DEUX natures d'au-delà, déclarées par le modèle (`duration_extension`) : la CONTINUATION
    // (le passage suivant reprend les dernières images — mouvement continu, zone ORANGE) et le
    // départ d'UNE image (extrapolé, transitions visibles — zone ROUGE).
    var continuation = ext === 'continuation';
    el.classList.add('wama-range-capped');
    el.classList.toggle('wama-range-capped--continuation', continuation);
    el.style.setProperty('--wama-cap-pct', pct + '%');
    var beyond = Number(el.value) > Number(cap);
    var level = continuation ? 'is-continued' : 'is-extrapolated';
    ['is-extrapolated', 'is-continued'].forEach(function (c) {
      if (row) row.classList.toggle(c, beyond && c === level);
      note.classList.toggle(c, beyond && c === level);
    });
    var limit = esc(_capLabel(cap, p, unit));
    note.innerHTML = beyond
      ? (continuation
          ? '<i class="fas fa-link me-1"></i>Au-delà de ' + limit + ' : continué par segments ' +
            'qui reprennent les dernières images — mouvement continu, dérive possible sur la durée'
          : '<i class="fas fa-triangle-exclamation me-1"></i>Au-delà de ' + limit +
            ' : prolongé par segments — fonctionnement extrapolé, continuité non garantie')
      : 'Natif jusqu\'à ' + limit + (continuation
          ? ' · au-delà (zone orange) : continué'
          : ' · au-delà (zone rouge) : prolongé, extrapolé');
  }

  function _bindCapFrom(container, schema, ctx) {
    // Les bornes de CE rendu, rejouables : `apply()` pose des valeurs par programme, sans
    // `change` — le modèle d'une modale de lot changeait sans que la borne suive (2026-10-02).
    container._wpCapApply = [];
    (schema || []).forEach(function (p) {
      var cf = p.cap_from;
      if (!cf || !cf.field || !cf.capability) return;
      if (p.contexts && p.contexts.indexOf(ctx) === -1) return;
      var el = container.querySelector('#' + CSS.escape(perCtx(p.dom_id, ctx) || ('wp-' + ctx + '-' + p.name)));
      if (!el) return;                       // ce réglage n'est pas rendu dans ce conteneur
      var modelP = (schema || []).filter(function (q) { return q.name === cf.field; })[0];
      var source = cf.source || (modelP && modelP.help_source);
      var sel = modelP && container.querySelector(
        '#' + CSS.escape(perCtx(modelP.dom_id, ctx) || ('wp-' + ctx + '-' + modelP.name)));
      if (!modelP || !source || !sel) {
        // La borne lie DEUX champs du même rendu. Le réglage est là, son champ modèle non
        // (volet découpé en plusieurs hôtes, schéma filtré) : la borne serait inactive EN
        // SILENCE — exactement le défaut qu'elle existe pour retirer. On le dit (2026-10-02).
        if (global.console) console.warn('[WamaParams] cap_from de « ' + p.name + ' » : le champ « ' +
          cf.field + ' » n\'est pas dans ce rendu (' + ctx + ') — borne inactive');
        return;
      }
      var row = el.closest('.wama-param');
      var note = document.createElement('div');
      note.className = 'wama-cap-note small mt-1';
      (row || el.parentNode).appendChild(note);
      _catalogCaps(source, cf.source ? '' : _catalogDomain(modelP)).then(function (capsByKey) {
        function apply() { _applyCap(el, note, row, p, cf, capsByKey[sel.value] || null); }
        container._wpCapApply.push(apply);
        sel.addEventListener('change', apply);
        el.addEventListener('input', apply);
        // Les options du select modèle arrivent souvent APRÈS le rendu (catalogue, décorateur
        // d'app) et sa valeur est posée par programme, sans `change` : on écoute le remplissage.
        sel.addEventListener('wama:options-filled', apply);
        if (global.MutationObserver) {
          new MutationObserver(function () { apply(); }).observe(sel, { childList: true });
        }
        apply();
      });
    });
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
        Promise.resolve(global.WamaModelHelp.fetchCatalogMeta(
            p.help_source, { query: _catalogDomain(p) })).then(function (meta) {
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
        else if (el.getAttribute('data-any-of')) val = el.value.split('|').filter(Boolean);
        else val = el.value;
      });
      return val;
    }
    // show_if : string « <champ> » (truthy) OU JSON {field, in:[…] | equals:… | not_equals:… }.
    // Jumeau serveur : `param_schema._show_if_met` — même vocabulaire, les deux changent ensemble.
    function parseCond(raw) {
      if (!raw) return null;
      try { const o = JSON.parse(raw); if (o && typeof o === 'object') return o; } catch (e) {}
      return { field: raw };   // legacy : nom de champ, condition = truthy
    }
    function met(cond, value) {
      const cur = arguments.length > 1 ? value : valByName(cond.field);
      // Une LISTE = « l'une de » : la condition vaut si l'une des valeurs la satisfait.
      if (Array.isArray(cur)) return cur.some(function (one) { return met(cond, one); });
      if (cond.in) return cond.in.map(String).indexOf(String(cur)) !== -1;
      if ('equals' in cond) return String(cur) === String(cond.equals);
      if ('not_equals' in cond) return String(cur) !== String(cond.not_equals);
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
    // Le nom montré d'un média désigné suit sa valeur (champ caché posé ci-dessus).
    container.querySelectorAll('[data-media-pick]').forEach(function (btn) {
      const field = document.getElementById(btn.getAttribute('data-media-pick'));
      const name = btn.querySelector('.wama-media-pick-name');
      if (field && name) name.textContent = _mediaShown(field.value) || 'Choisir dans la médiathèque…';
    });
    _syncIntentSliders(container);   // curseur d'intention : hidden → position + tricolore
    _bindConditional(container);
    // Bornes par capacité du modèle (`cap_from`) : rejouées sur les valeurs qu'on vient de poser.
    (container._wpCapApply || []).forEach(function (replay) { replay(); });
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
  //   }) → { modal, host, form }   (remplace la modale existante de même id ; `settingsModal`
  //                                 la retire de la page à la fermeture)
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
      '  <div class="modal-content bg-body text-body-emphasis border-secondary">' +
      '    <div class="modal-header border-secondary">' +
      '      <h5 class="modal-title">' +
      (cfg.titleIcon ? '<i class="fas ' + esc(cfg.titleIcon) + ' me-2"></i>' : '') +
      esc(cfg.title || 'Paramètres') + '</h5>' +
      '      <button type="button" class="btn-close" data-bs-dismiss="modal"></button>' +
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
  // ── PORTÉE d'une modale : les réglages d'UN process (P5, ROUTE §10.6 5.1 — 2026-10-03) ──
  // Le ⚙ d'une ligne de process (`_card_processes.html`) est le MÊME bouton que le ⚙ de la
  // card : l'app déclare un seul ouvreur, qui appelle `settingsModal` sans rien savoir du
  // process. La portée se pose donc JUSTE AVANT, pour le prochain appel (`queue-actions.js`
  // la lit sur `data-only`), et s'éteint seule si aucune modale ne la consomme à temps — un
  // ouvreur qui attend le réseau avant d'ouvrir a trois secondes, une modale ouverte plus tard
  // par un autre geste ne doit pas en hériter.
  let pendingScope = null;

  function scopeNextModal(names, label) {
    const kept = (names || []).filter(Boolean);
    pendingScope = kept.length ? { names: kept, label: label || '', until: Date.now() + 3000 } : null;
  }

  function takeScope() {
    const scope = pendingScope;
    pendingScope = null;
    return (scope && scope.until >= Date.now()) ? scope : null;
  }

  // Le schéma RÉDUIT aux réglages nommés — plus les porteurs `hidden` (ex. `media_type`), qui
  // conditionnent l'affichage des autres et ne se montrent pas, et le champ qui COMMANDE le
  // `show_if` d'un réglage retenu (2026-10-13) : sans lui la condition ne se juge pas, et le
  // réglage restait masqué — le type de résumé dans le ⚙ du process « Résumé », que
  // l'interrupteur du résumé commande. Les groupes sans champ restant sortent avec eux.
  // Pure (testée en V8, `tests_cap_from_js`).
  function scopedSchema(schema, names) {
    const wanted = {};
    (names || []).forEach(function (n) { wanted[n] = true; });
    const controller = function (p) {
      const cond = p.show_if;
      return cond ? (typeof cond === 'object' ? cond.field : cond) : null;
    };
    let grew = true;
    while (grew) {                       // une commande peut avoir sa propre commande
      grew = false;
      (schema || []).forEach(function (p) {
        const field = wanted[p.name] && controller(p);
        if (field && !wanted[field]) { wanted[field] = true; grew = true; }
      });
    }
    return (schema || []).filter(function (p) { return p.type === 'hidden' || wanted[p.name]; });
  }

  function scopedGroups(groups, schema) {
    const used = {};
    (schema || []).forEach(function (p) { if (p.group) used[p.group] = true; });
    return (groups || []).filter(function (g) { return used[g.key || g.id || g.group || g.name]; });
  }

  // La configuration d'une modale SOUS PORTÉE — pure (testée en V8, `tests_cap_from_js`).
  function scopedConfig(cfg, scope) {
    if (!scope) return cfg;
    return Object.assign({}, cfg, {
      schema: scopedSchema(cfg.schema, scope.names),
      groups: scopedGroups(cfg.groups, scopedSchema(cfg.schema, scope.names)),
      title: (cfg.title || 'Paramètres') + (scope.label ? ' — ' + scope.label : ''),
      // Les zones d'app HORS schéma (prompt, classes à flouter, résolution…) ne sont pas
      // des réglages de CE process : une modale à portée ne rend que le schéma réduit.
      // `collect` reste appelé — il ne poste que ce qu'il trouve, et porte le drapeau de
      // relance de certaines apps.
      decorate: null,
    });
  }

  function settingsModal(cfg) {
    cfg = scopedConfig(cfg || {}, takeScope());
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

      // Fermée, la modale QUITTE la page (2026-10-21, card 1532 de l'avatarizer). Ses champs
      // portent les ids du schéma (`dom_id`), les mêmes d'une card à l'autre : la modale d'une
      // card ouverte avant restait cachée dans le DOM, et tout ce qui résout un champ par
      // `getElementById` (sources d'options, WamaModelCaps, WamaInputMatch) visait SES champs.
      // Mesuré : le ⚙ d'une seconde card s'ouvrait sur un select de modèle TTS VIDE jusqu'au F5.
      // `renderSettingsModal` ne retirait que la modale de même id. Précédent : `WamaApp.confirm`.
      const bs = new bootstrap.Modal(modal);
      modal.addEventListener('hidden.bs.modal', function () {
        bs.dispose();
        modal.remove();
      });
      bs.show();
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

  // ── « ↺ Par défaut » : remet le FORMULAIRE aux défauts du schéma — la moitié CLIENTE
  // du modèle ÉVÉNEMENTIEL (Fabien, 02/09, ROADMAP §23.2quater : reset/preset/profil sont
  // des GESTES qui écrasent, le dernier geste gagne). Délibérément SANS réseau : le reset
  // remplit le formulaire, l'utilisateur VOIT l'effet réel avant d'Enregistrer (qui écrit).
  // Champs sans default : remis au NEUTRE de leur type ('' / décoché) — un reset partiel
  // qui laisserait les autres champs en l'état ne serait pas « tout remettre à plat ».
  function applyDefaults(host, schema, context) {
    const ctx = context || 'item';
    const vals = {};
    (schema || []).forEach(function (p) {
      if (p.contexts && p.contexts.indexOf(ctx) === -1) return;
      if (p.type === 'hidden') return;              // les porteurs (media_type) ne se resettent pas
      vals[p.name] = (p.default !== undefined && p.default !== null) ? p.default
                   : (p.type === 'toggle' ? false : '');
    });
    apply(host, vals);
    return vals;
  }

  global.WamaParams = { render: render, read: read, apply: apply,
                        applyDefaults: applyDefaults,
                        // La règle `cap_from` elle-même (bornes, zones, champ imposé) — exposée
                        // pour que sa garde (`tests_cap_from_js`, V8) l'exerce sans navigateur.
                        applyCapFrom: _applyCap,
                        // …et son CÂBLAGE (champ modèle absent du rendu → dit ; valeurs posées
                        // par `apply` → borne rejouée), pour la même garde.
                        bindCapFrom: _bindCapFrom,
                        // La visibilité `show_if` — exposée pour la garde de PARITÉ avec son
                        // jumeau serveur `param_schema._show_if_met` (`tests_cap_from_js`).
                        bindConditional: _bindConditional,
                        // Libellé d'une valeur (`display_format`) — appelé par l'`oninput` du
                        // curseur rendu ; `proposedValue`/`bindDefaultFrom` : la règle de
                        // `default_from`, exposée pour sa garde V8.
                        valueLabel: valueLabel,
                        proposedValue: _proposedValue,
                        bindDefaultFrom: _bindDefaultFrom,
                        renderSettingsModal: renderSettingsModal,
                        settingsModal: settingsModal,
                        // Portée d'une modale au ⚙ d'un process (P5) : posée par la brique des
                        // actions, consommée par le prochain `settingsModal` ; `scopedSchema`
                        // est la règle pure, exposée pour sa garde V8.
                        scopeNextModal: scopeNextModal,
                        scopedSchema: scopedSchema,
                        scopedConfig: scopedConfig,
                        takeModalScope: takeScope,
                        // Extension du vocabulaire de composants SANS toucher au moteur :
                        // un type absent du registry retombe sur le champ texte (jamais d'erreur).
                        registerRenderer: registerRenderer,
                        // Un `change` est-il une DÉCISION de l'utilisateur (geste, choix dans
                        // la médiathèque) ou un remplissage du moteur ? Pour qui enregistre.
                        isGesture: isGesture,
                        // Sources d'options adossées à une donnée de page (cf. PAGE_OPTION_SOURCES) —
                        // exposé pour qu'un optionsResolver (d'app ou GÉNÉRÉ) délègue au registre
                        // commun au lieu de réécrire la même résolution.
                        resolvePageOptions: resolvePageOptions,
                        // Exposé pour le VOLET (WamaInspector.initFromSchema) : un select de
                        // volet rendu serveur reçoit lui aussi ses options du catalogue
                        // (+ « auto » et sa prévision) — sans ça, seules les modales,
                        // rendues par render(), passaient par les sources d'options.
                        bindOptionSources: _bindOptionSources,
                        // Le texte de la prévision « auto » (provenance comprise) — exposé pour
                        // sa garde V8 (`tests_auto_model.PreviewOriginTest`).
                        autoPreviewText: _autoPreviewText,
                        rendererTypes: function () { return Object.keys(RENDERERS); } };
})(window);
