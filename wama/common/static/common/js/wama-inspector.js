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
    var u = escapeHtml(url);  // sécurise l'attribut src/href (guillemets, noms spéciaux)
    if (mime.indexOf('image/') === 0) {
      media = '<img src="' + u + '" alt="" class="wama-inspector-preview-media" style="max-width:100%;max-height:220px;border-radius:6px;">';
    } else if (mime.indexOf('video/') === 0) {
      media = '<video src="' + u + '" controls ' + (autoplay ? 'autoplay muted ' : '') +
        'class="wama-inspector-preview-media" style="max-width:100%;max-height:220px;border-radius:6px;"></video>';
    } else if (mime.indexOf('audio/') === 0) {
      if (global.WamaAudioPlayer && WamaAudioPlayer.create) {
        host.innerHTML = '';
        try {
          host.appendChild(WamaAudioPlayer.create(url, 'insp', { autoplay: !!autoplay }));
          // Pics serveur (common/utils/waveform.compute_peaks) : onde dessinée SANS décoder
          // (fichiers longs) ou qui se CONSTRUIT (streaming « pendant »). setPeaks normalise
          // l'échelle uint8→0-1. Additif : sans data.peaks, comportement inchangé.
          if (Array.isArray(data.peaks) && data.peaks.length && WamaAudioPlayer.setPeaks) {
            WamaAudioPlayer.setPeaks('insp', data.peaks);
          }
        }
        catch (e) { host.innerHTML = '<audio src="' + u + '" controls ' + (autoplay ? 'autoplay ' : '') + 'style="width:100%;"></audio>'; }
        _previewCaption(host, name);
        return;
      }
      media = '<audio src="' + u + '" controls ' + (autoplay ? 'autoplay ' : '') + 'style="width:100%;"></audio>';
    } else if (mime === 'application/pdf') {
      media = '<embed src="' + u + '" type="application/pdf" style="width:100%;height:220px;border-radius:6px;">';
    } else if (mime === 'text/html') {
      // HTML : iframe SANDBOXÉE (pas de script, pas de navigation) — aperçu sûr.
      media = '<iframe src="' + u + '" sandbox class="wama-inspector-preview-media" ' +
        'style="width:100%;height:220px;border:0;background:#fff;border-radius:6px;"></iframe>';
    } else if (mime.indexOf('text/') === 0) {
      // Texte (plain/markdown/csv… ; ex. le PROMPT en entrée). Contenu inline si fourni
      // (data.content, cas prompt sans fichier), sinon chargé en async depuis l'URL.
      host.innerHTML = '<div class="wama-inspector-preview"><pre class="small text-white-50 text-start mb-1" ' +
        'style="max-height:200px;overflow:auto;white-space:pre-wrap;word-break:break-word;">…</pre></div>';
      var pre = host.querySelector('pre');
      var _renderText = function (t) {
        if (pre) pre.textContent = (t && t.length > 3000) ? t.slice(0, 3000) + '\n…' : (t || '(vide)');
      };
      if (typeof data.content === 'string') {
        _renderText(data.content);
      } else {
        fetch(url).then(function (r) { return r.ok ? r.text() : ''; }).then(_renderText)
          .catch(function () { if (pre) pre.textContent = '(aperçu indisponible)'; });
      }
      _previewCaption(host, name, data);
      return;
    } else {
      media = '<a href="' + u + '" target="_blank" rel="noopener" class="btn btn-sm btn-outline-info">' +
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
  var DETAIL_ORDER = ['source_duration_display', 'engine', 'engine_effective', 'output_format', 'output_quality', 'processing_time_display'];
  function _detailChip(icon, value, label) {
    // Inspecteur = vue détaillée : le LABEL est VISIBLE (contrairement aux chips de card, denses).
    var lbl = label ? '<span class="opacity-75">' + escapeHtml(label) + '</span> ' : '';
    return '<span class="wama-chip" title="' + escapeHtml(label || '') + '"><i class="fas ' + icon + '"></i> ' + lbl + escapeHtml(value) + '</span>';
  }
  function renderDetailChips(d) {
    var st = (d.status || '').toUpperCase();
    var stCls = st === 'SUCCESS' ? 'success' : st === 'FAILURE' ? 'danger' : st === 'RUNNING' ? 'warning text-dark' : 'secondary';
    var stLbl = (global.WamaApp && WamaApp.STATUS_LABEL && WamaApp.STATUS_LABEL[st]) || st;
    var head = '<div class="d-flex align-items-center gap-2 flex-wrap mb-1">';
    if (d.id != null) head += '<strong class="text-light">#' + escapeHtml(d.id) + '</strong>';
    if (st) head += '<span class="badge bg-' + stCls + '">' + escapeHtml(stLbl) + '</span>';
    if (d.created_at) head += '<small class="text-white-50"><i class="fas fa-calendar-alt"></i> ' + escapeHtml(d.created_at) + '</small>';
    head += '<button type="button" class="btn btn-sm btn-link text-white-50 p-0 ms-auto wama-info-deselect" title="Fermer la sélection"><i class="fas fa-xmark"></i></button>';
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
    var mediaSection = document.getElementById('media-section');  // section Médias/aperçu (n'a de sens que pour un ITEM)
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
        // Identité + désélection remontées ici → le bandeau Paramètres (#N redondant) est masqué.
        // (Apps portées au détail : le bandeau est RETIRÉ du template — §21.3.6 ; on ne proxifie
        // donc plus par son bouton, le ✕ des Infos appelle la désélection directement.)
        var banner = $(ids.banner);
        if (banner) banner.style.display = 'none';
        var db = infoHost.querySelector('.wama-info-deselect');
        if (db) db.addEventListener('click', deselect);
      }).catch(hideDetail);
    }
    var _duringTimer = null;
    function _stopDuring() { if (_duringTimer) { clearInterval(_duringTimer); _duringTimer = null; } }

    // Double-clic sur l'aperçu → PLEIN ÉCRAN via la modale commune (WamaMediaPreview, PAS de
    // réinvention) + icône overlay indicative. Le texte inline (prompt/sortie) passe par text_content.
    function _attachFullscreen(d, baseUrl) {
      if (!previewHost || typeof global.showPreviewModal !== 'function') return;
      previewHost.style.position = previewHost.style.position || 'relative';
      previewHost.title = 'Double-clic : plein écran';
      previewHost.ondblclick = function () {
        try {
          // Transmet baseUrl + sides + side : la modale reconstruit le toggle Entrée/Comparer/Sortie.
          var m = (d.content && !d.url)
            ? { text_content: d.content, name: d.name || 'Texte', mime_type: 'text/plain' }
            : d;
          m._baseUrl = baseUrl; m.sides = d.sides; m.side = d.side;
          global.showPreviewModal(m);
        } catch (e) { /* no-op */ }
      };
      if (!previewHost.querySelector('.wama-preview-expand')) {
        var ic = document.createElement('div');
        ic.className = 'wama-preview-expand';
        ic.innerHTML = '<i class="fas fa-expand"></i>';
        ic.style.cssText = 'position:absolute;top:6px;right:6px;opacity:.55;pointer-events:none;font-size:.8rem;';
        previewHost.appendChild(ic);
      }
    }

    function restorePreview() {
      _stopDuring();
      if (previewHost) previewHost.innerHTML = previewPlaceholder;
      if (previewTitleEl) previewTitleEl.textContent = previewTitleDefault;
    }
    function fillPreview(card, title) {
      _stopDuring();
      if (!previewHost || !card) return;
      var link = (card.matches && card.matches('[data-preview-url]')) ? card : card.querySelector('[data-preview-url]');
      var url = link && link.getAttribute('data-preview-url');
      if (!url) { restorePreview(); return; }
      // Défaut INTELLIGENT (2026-07-12) : item terminé → on demande la SORTIE (le serveur
      // replie sur l'entrée si l'app n'a pas de result_file). Sinon : entrée.
      var status = (card.dataset && card.dataset.status) || '';
      var side = (status === 'SUCCESS') ? 'output' : 'input';
      _fetchPreviewSide(url, side, title);
      // Phase PENDANT (COMMUN, toute app) : item en cours + app qui streame (during_capable) →
      // on suit l'aperçu partiel qui se CONSTRUIT. Auto-arrêt si l'app ne streame pas.
      if (status === 'RUNNING' || status === 'PROCESSING') _startDuring(url, card, title);
    }

    function _startDuring(baseUrl, card, title) {
      _stopDuring();
      var tick = function () {
        var st = card && card.dataset && card.dataset.status;
        if (st !== 'RUNNING' && st !== 'PROCESSING') {   // terminé → bascule sur la SORTIE
          _stopDuring();
          _fetchPreviewSide(baseUrl, 'output', title);
          return;
        }
        var u = baseUrl + (baseUrl.indexOf('?') === -1 ? '?' : '&') + 'side=during';
        fetch(u).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
          if (!d || !d.sides || !d.sides.during_capable) { _stopDuring(); return; }  // ne streame pas → stop
          if (d.sides.has_during) renderInlinePreview(previewHost, d, false);
        }).catch(function () {});
      };
      _duringTimer = setInterval(tick, 1300);
      tick();
    }

    function _fetchPreviewSide(baseUrl, side, title) {
      var u = baseUrl + (baseUrl.indexOf('?') === -1 ? '?' : '&') + 'side=' + side;
      fetch(u).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
        // accepte une face à URL (média), à CONTENU inline (prompt texte) OU à PICS (streaming)
        if (!d || (!d.url && !d.content && !(d.peaks && d.peaks.length))) { restorePreview(); return; }
        var autoplay = (cfg.autoplay != null) ? cfg.autoplay : global.WAMA_INSPECTOR_AUTOPLAY;
        renderInlinePreview(previewHost, d, !!autoplay);
        _attachFullscreen(d, baseUrl);
        _renderSideToggle(baseUrl, d, title);
        if (previewTitleEl && title) previewTitleEl.textContent = title;
      }).catch(restorePreview);
    }

    // Toggle [Entrée | Sortie | Comparer] — générique (clés canoniques source_file/result_file,
    // méta `sides` de unified_preview). Comparer = slider image/image (STUDIO_VISION 2026-07-12).
    function _renderSideToggle(baseUrl, d, title) {
      var s = d.sides;
      if (!s || !s.has_input || !s.has_output) return;
      var bar = document.createElement('div');
      bar.className = 'btn-group btn-group-sm wama-preview-sides mt-1 w-100';   // pleine largeur
      function mk(label, icon, active, onClick) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'btn py-0 px-2 flex-fill ' + (active ? 'btn-info' : 'btn-outline-info');
        b.innerHTML = '<i class="fas ' + icon + ' me-1"></i>' + label;
        b.addEventListener('click', onClick);
        return b;
      }
      // Ordre CHRONOLOGIQUE (2026-07-21) : Entrée → Comparer → Sortie.
      bar.appendChild(mk('Entrée', 'fa-right-to-bracket', d.side === 'input', function () {
        _fetchPreviewSide(baseUrl, 'input', title);
      }));
      if (s.comparable) {
        bar.appendChild(mk('Comparer', 'fa-left-right', d.side === 'compare', function () {
          _renderCompare(baseUrl, title);
        }));
      }
      bar.appendChild(mk('Sortie', 'fa-flag-checkered', d.side === 'output', function () {
        _fetchPreviewSide(baseUrl, 'output', title);
      }));
      previewHost.appendChild(bar);
    }

    // Slider comparatif entrée/sortie (V1 : images) — l'image SORTIE est rognée par un
    // conteneur dont la largeur suit le curseur ; les deux images ont la même géométrie.
    function _renderCompare(baseUrl, title) {
      var sep = baseUrl.indexOf('?') === -1 ? '?' : '&';
      Promise.all([
        fetch(baseUrl + sep + 'side=input').then(function (r) { return r.json(); }),
        fetch(baseUrl + sep + 'side=output').then(function (r) { return r.json(); }),
      ]).then(function (both) {
        var inD = both[0], outD = both[1];
        if (!inD || !outD || !inD.url || !outD.url) return;
        previewHost.innerHTML = '';
        var wrap = document.createElement('div');
        wrap.className = 'wama-compare';
        wrap.innerHTML =
          '<img class="wama-compare-base" src="' + inD.url + '" alt="Entrée">' +
          '<div class="wama-compare-top"><img src="' + outD.url + '" alt="Sortie"></div>' +
          '<span class="wama-compare-badge in">Entrée</span>' +
          '<span class="wama-compare-badge out">Sortie</span>';
        previewHost.appendChild(wrap);
        var range = document.createElement('input');
        range.type = 'range';
        range.min = 0; range.max = 100; range.value = 50;
        range.className = 'form-range wama-compare-range';
        previewHost.appendChild(range);
        var base = wrap.querySelector('.wama-compare-base');
        var top = wrap.querySelector('.wama-compare-top');
        var topImg = top.querySelector('img');
        function sync() {
          topImg.style.width = base.clientWidth + 'px';
          top.style.width = range.value + '%';
        }
        base.addEventListener('load', sync);
        range.addEventListener('input', sync);
        if (base.complete) sync();
        _renderSideToggle(baseUrl, { side: 'compare', sides: { has_input: true, has_output: true, comparable: true } }, title);
      });
    }

    // Agrégats (file / batch) affichés dans la section Infos quand rien / un batch est sélectionné.
    // Compteurs NON recomptes : on LIT les sources serveur uniques.
    // File -> window.WamaQueueStats (wama-global-progress.js). Batch -> data-* de la card mere
    // (_batch_card.html, depuis build_batches_list). Une source, plusieurs vues.
    function _fileCounts() {
      var s = global.WamaQueueStats;
      if (!s) return null;
      var t = s.total || 0, d = s.done || 0, r = s.running || 0, f = s.failed || 0;
      return { total: t, success: d, running: r, failure: f, pending: Math.max(0, t - d - r - f) };
    }
    function _batchCounts(group) {
      var h = group && group.querySelector('[data-batch-total]');
      if (!h) return { total: 0, success: 0, running: 0, failure: 0, pending: 0 };
      var n = function (a) { return parseInt(h.getAttribute(a) || '0', 10) || 0; };
      var t = n('data-batch-total'), su = n('data-batch-success'), ru = n('data-batch-running'), fa = n('data-batch-failure');
      return { total: t, success: su, running: ru, failure: fa, pending: Math.max(0, t - su - ru - fa) };
    }
    function _renderAggInfo(label, c) {
      var chip = function (icon, n) { return '<span class="wama-chip"><i class="fas ' + icon + '"></i> ' + n + '</span>'; };
      var chips = chip('fa-layer-group', 'Total ' + c.total)
        + (c.success ? '<span class="wama-chip"><i class="fas fa-check text-success"></i> ' + c.success + '</span>' : '')
        + (c.running ? '<span class="wama-chip"><i class="fas fa-spinner text-warning"></i> ' + c.running + '</span>' : '')
        + (c.pending ? '<span class="wama-chip"><i class="fas fa-clock text-white-50"></i> ' + c.pending + '</span>' : '')
        + (c.failure ? '<span class="wama-chip"><i class="fas fa-xmark text-danger"></i> ' + c.failure + '</span>' : '');
      return '<div class="small text-white-50 mb-1">' + label + '</div><div class="d-flex flex-wrap gap-1">' + chips + '</div>';
    }
    function showQueueInfo() {
      if (mediaSection) mediaSection.style.display = 'none';
      if (!infoHost) return;
      var c = _fileCounts();
      if (!c || !c.total) { hideDetail(); return; }
      infoHost.innerHTML = _renderAggInfo('<i class="fas fa-list text-info"></i> File · ' + c.total + ' élément' + (c.total > 1 ? 's' : ''), c);
      if (infoSection) infoSection.style.display = '';
      var banner = $(ids.banner); if (banner) banner.style.display = '';
    }
    function showBatchInfo(bid, group) {
      if (mediaSection) mediaSection.style.display = 'none';
      if (!infoHost) return;
      var c = _batchCounts(group);
      infoHost.innerHTML = '<div class="d-flex align-items-center gap-2 mb-1"><strong class="text-light">Batch #' + escapeHtml(bid) + '</strong>'
        + '<button type="button" class="btn btn-sm btn-link text-white-50 p-0 ms-auto wama-info-deselect" title="Fermer la sélection"><i class="fas fa-xmark"></i></button></div>'
        + _renderAggInfo('<i class="fas fa-layer-group text-info"></i> ' + c.total + ' élément' + (c.total > 1 ? 's' : ''), c);
      if (infoSection) infoSection.style.display = '';
      var banner = $(ids.banner); if (banner) banner.style.display = 'none';
      var db = infoHost.querySelector('.wama-info-deselect');
      if (db) db.addEventListener('click', function () { var od = $(ids.deselect); if (od) od.click(); });
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
      if (mediaSection) mediaSection.style.display = '';
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
      showBatchInfo(bid, group);
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
      showQueueInfo();
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

    try { showQueueInfo(); } catch (e) {}
    document.addEventListener('media:processed', function () {
      if (itemId == null && batchId == null) { try { showQueueInfo(); } catch (e) {} }
    });

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
    // name= du groupe radio (radio_name legacy, même sémantique par contexte que dom_id),
    // repli sur panelKey — sans ça les radios à nom legacy (ex. transcriber globalSummaryType)
    // échappent au read/apply dérivés.
    function radioKey(p) {
      const r = p.radio_name;
      const k = (r && typeof r === 'object') ? (r.panel || '') : (r || '');
      return k || panelKey(p);
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
          const radios = (ph || document).querySelectorAll('input[type="radio"][name="' + radioKey(p) + '"]');
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
          const radios = (ph || document).querySelectorAll('input[type="radio"][name="' + radioKey(p) + '"]');
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
