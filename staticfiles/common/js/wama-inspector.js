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
 *     showOnInspect: ['actions-section'],   // ids masqués TANT QUE rien n'est sélectionné
 *                                           // (une section d'actions vide ne doit pas s'afficher)
 *     settingsTitleSelector, settingsTitleInspect,        // titre de section contextualisé
 *     panel: { read(), apply(values) },     // lecture/écriture du formulaire du volet
 *     cardSettings(card) -> values,         // extrait les réglages d'une card (data-*)
 *     renderItemActions(host, card),        // remplit le conteneur d'actions pour une card
 *     renderBatchActions(host, batchId),    // ... pour un batch
 *     onDeselect(),                         // pendant : remise à l'état « aucune sélection »
 *                                           // (appelé quel que soit le chemin : croix, Échap…)
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

  // Actions d'un LOT : résout la card mère depuis son IDENTIFIANT, puis clone ses boutons.
  //
  // ⚠⚠ Existe parce que le contrat était INVERSÉ dans 4 apps (2026-08-26). `fillActions` passe
  // un IDENTIFIANT (`renderBatchActions(host, batchId)`, cf. l'en-tête de ce fichier) ; or
  // anonymizer, avatarizer, enhancer (×2) et synthesizer écrivaient `function (host, group)`
  // puis `group.querySelector(...)` — c'est-à-dire qu'elles attendaient un ÉLÉMENT DOM. Un
  // clic sur une card mère y levait `TypeError: group.querySelector is not a function`, et le
  // volet Actions restait vide.
  //
  // ⚠ Ce n'était PAS théorique : mesuré le 26/08, `anonymizer` (2 lots, jusqu'à 8 éléments) et
  // `synthesizer` (3 lots, jusqu'à 39) portaient de vrais lots multi-éléments sur le compte de
  // Fabien. Le nocturne ne le voyait pas — `batch_actions` clique les boutons de la card sans
  // passer par la SÉLECTION, qui est le chemin qui lève.
  //
  // Les apps au contrat correct recopiaient ces 3 lignes à l'identique : le geste est commun,
  // il vit donc ici. ✅ PORTAGE TERMINÉ le 2026-08-26 — 10 apps sur 10 passent par ce helper.
  //
  // ⚠ Le relevé du 26/08 nommait « transcriber, converter, describer, reader, imager » ; la
  // mesure site par site en a corrigé DEUX : `composer` était un 6ᵉ site (il résolvait la card
  // mère par un BOUTON portant data-batch-id puis `.closest()` — survivance d'avant
  // `_queue_entry.html`), et `imager` ne déclarait AUCUN callback d'actions, ni item ni batch :
  // son volet Actions était VIDE, en silence. Une liste par motif oriente ; elle ne conclut pas.
  function cloneBatchActions(host, batchId, label) {
    var groupe = document.querySelector('.batch-group[data-batch-id="' + batchId + '"]');
    cloneActions(host, groupe ? groupe.querySelector('.btn-group-actions') : null,
      label || '<i class="fas fa-layer-group text-info"></i> Actions — batch #' + batchId);
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // ── DENSITÉ d'un aperçu texte, DÉCLARÉE par l'hôte (2026-08-22) ───────────────────────
  // Un volet et une CARD n'ont pas la même densité : le volet peut dérouler 3000 caractères
  // dans un <pre> scrollable, une card veut un extrait NU de quelques centaines de signes.
  // Cette différence était jusqu'ici résolue en RÉÉCRIVANT l'extrait dans chaque gabarit —
  // describer 400 (.result-preview), reader 400 (.reader-preview + filtre compact_preview),
  // transcriber 160 (.wama-card-preview) : trois longueurs, trois classes, trois bouts de
  // markup pour un seul et même geste. L'hôte la DÉCLARE désormais, le commun la rend.
  //   data-preview-mode="excerpt"     → extrait nu (pas de <pre>, pas de légende)
  //   data-preview-max-chars="400"    → longueur, propre à la card
  // Absent = comportement d'AVANT, à l'identique (volet et adoptants du 18/08 intacts).
  var TEXTE_MAX_VOLET = 3000, TEXTE_MAX_CARD = 400;

  function _densitePreview(host) {
    var d = (host && host.dataset) || {};
    var mode = d.previewMode || 'rich';
    var max = parseInt(d.previewMaxChars, 10);
    if (!(max > 0)) max = (mode === 'excerpt') ? TEXTE_MAX_CARD : TEXTE_MAX_VOLET;
    return { mode: mode, max: max };
  }

  // Compactage pour extrait de card : syntaxe markdown retirée, blancs écrasés. MIROIR CLIENT
  // du filtre `compact_preview` de reader (reader_tags.py:8) — même traitement, mêmes étapes,
  // dans le même ordre. Il devient inutile dans les gabarits : un extrait rendu par le commun
  // ne peut plus dépendre d'un filtre que seul reader possède.
  function _compacteTexte(t) {
    return String(t == null ? '' : t)
      .replace(/^#{1,6}\s+/gm, '')
      .replace(/\*{1,3}|_{1,3}/g, '')
      .replace(/^\s*[-*+]\s+/gm, '')
      .replace(/\|/g, ' ')
      .replace(/`+/g, '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  // ── Sortie MULTIPLE : grille de vignettes (2026-08-22) ────────────────────────────────
  // Rend la clé canonique `result_files` (N fichiers issus d'UN traitement — imager génère N
  // images). Remplace les boucles d'<img> écrites par app.
  // La NAVIGATION de la visionneuse est nourrie par la COLLECTION elle-même, jamais par un
  // balayage du DOM : imager collectait `.generated-image-preview img` alors que la classe est
  // SUR le <img>, donc sa collecte rendait 0 et la visionneuse retombait silencieusement sur
  // « image seule, sans navigation » (constaté 22/08). Ici la liste vient de la donnée, elle
  // ne peut pas se désaccorder du markup.
  function _renderPreviewGrid(host, files) {
    host.innerHTML = '';
    var grille = document.createElement('div');
    grille.className = 'wama-preview-grid d-flex flex-wrap gap-2';
    files.forEach(function (f, i) {
      var mime = (f.mime_type || '').toLowerCase();
      var tuile;
      if (mime.indexOf('video/') === 0) {
        tuile = document.createElement('video');
        tuile.src = f.url;
        tuile.preload = 'metadata';
      } else {
        tuile = document.createElement('img');
        tuile.src = f.url;
        tuile.alt = f.name || '';
      }
      tuile.className = 'wama-preview-tile img-thumbnail bg-dark border-secondary';
      tuile.title = f.name || '';
      tuile.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();          // ne pas voler le clic de sélection de la card
        if (global.showPreviewModalWithNav) global.showPreviewModalWithNav(f, files, i);
        else if (global.showPreviewModal) global.showPreviewModal(f);
      });
      grille.appendChild(tuile);
    });
    host.appendChild(grille);
    _previewCaption(host, files.length + ' fichiers');
  }

  // Rendu INLINE compact d'un aperçu média dans le volet (≠ modale plein écran de media-preview.js).
  // Données = JSON de common:unified_preview {name, url, mime_type, …}. autoplay gated par le profil
  // (jamais de génération : on n'affiche que l'existant — CARD_DESIGN §10.6 / décision Fabien).
  function renderInlinePreview(host, data, autoplay) {
    if (!host) return;
    // Collection AVANT l'aiguillage par mime : `files` décrit N sorties, `mime_type` ne décrit
    // que le représentant — trancher sur le mime ferait rendre une seule vignette.
    if (Array.isArray(data.files) && data.files.length > 1) {
      _renderPreviewGrid(host, data.files);
      return;
    }
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
        // playerId : data-player-id de l'hôte si fourni (previews DANS les cards — N players
        // simultanés), repli 'insp' (volet inspecteur, hôte unique). 18/08.
        var pid = (host.dataset && host.dataset.playerId) || 'insp';
        host.innerHTML = '';
        try {
          host.appendChild(WamaAudioPlayer.create(url, pid, { autoplay: !!autoplay }));
          // Pics serveur (common/utils/waveform.compute_peaks) : onde dessinée SANS décoder
          // (fichiers longs) ou qui se CONSTRUIT (streaming « pendant »). setPeaks normalise
          // l'échelle uint8→0-1. Additif : sans data.peaks, comportement inchangé.
          if (Array.isArray(data.peaks) && data.peaks.length && WamaAudioPlayer.setPeaks) {
            WamaAudioPlayer.setPeaks(pid, data.peaks);
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
      var dens = _densitePreview(host);
      if (dens.mode === 'excerpt') {
        // EXTRAIT de card : texte nu dans l'hôte lui-même — ni <pre> scrollable ni légende,
        // qui sont la densité du volet. On écrit dans l'hôte SANS toucher à ses classes ni à
        // ses attributs : c'est ce qui préserve les gestes déjà posés par les apps dessus
        // (reader = data-action="expand" + double-clic texte intégral, transcriber = double-clic
        // overlay via .wama-card-preview, describer = .result-preview où son polling écrit le
        // texte partiel pendant le RUN). Tous ces contrats portent sur l'ÉLÉMENT, aucun sur son
        // contenu — vérifié consommateur par consommateur avant le portage.
        var _extrait = function (t) {
          var c = _compacteTexte(t);
          host.textContent = c ? (c.length > dens.max ? c.slice(0, dens.max) + ' …' : c) : '(vide)';
        };
        if (typeof data.content === 'string') {
          _extrait(data.content);
        } else {
          fetch(url).then(function (r) { return r.ok ? r.text() : ''; }).then(_extrait)
            .catch(function () { /* best-effort : la card reste lisible sans extrait */ });
        }
        return;
      }
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
  // Basename LISIBLE d'un chemin/URL : l'URL média percent-encode les accents (%C3%A9…) —
  // on décode pour l'AFFICHAGE (constat Fabien 17/08, « Au_th%C3%A9%C3%A2tre_… ») ; le lien
  // href, lui, garde l'URL encodée. Fallback brut si séquence invalide.
  function _basename(p) {
    var n = String(p).split('/').pop();
    try { return decodeURIComponent(n); } catch (e) { return n; }
  }
  function _detailChip(icon, value, label) {
    // Inspecteur = vue détaillée : le LABEL est VISIBLE (contrairement aux chips de card, denses).
    var lbl = label ? '<span class="opacity-75">' + escapeHtml(label) + '</span> ' : '';
    return '<span class="wama-chip" title="' + escapeHtml(label || '') + '"><i class="fas ' + icon + '"></i> ' + lbl + escapeHtml(value) + '</span>';
  }
  // Groupement par SECTION — miroir de l'anatomie card v3 (CARD_DESIGN §11 : Entrée /
  // Réglages / Sortie ; l'ÉTAT vit dans l'en-tête id+badge+date+temps). Décision Fabien
  // 18/08 : les chips « en vrac » sur une seule rangée étaient illisibles.
  function _chipRow(chips) {
    return chips.length ? '<div class="d-flex flex-wrap gap-1">' + chips.join('') + '</div>' : '';
  }
  function _section(label, inner) {
    return inner ? '<div class="wama-insp-sec"><span class="wama-insp-sec-lbl">' + label + '</span>' + inner + '</div>' : '';
  }
  function renderDetailChips(d, ctx) {
    var st = (d.status || '').toUpperCase();
    var stCls = st === 'SUCCESS' ? 'success' : st === 'FAILURE' ? 'danger' : st === 'RUNNING' ? 'warning text-dark' : 'secondary';
    var stLbl = (global.WamaApp && WamaApp.STATUS_LABEL && WamaApp.STATUS_LABEL[st]) || st;
    var head = '<div class="d-flex align-items-center gap-2 flex-wrap mb-1">';
    if (d.id != null) head += '<strong class="text-light">#' + escapeHtml(d.id) + '</strong>';
    if (st) head += '<span class="badge bg-' + stCls + '">' + escapeHtml(stLbl) + '</span>';
    if (d.created_at) head += '<small class="text-white-50"><i class="fas fa-calendar-alt"></i> ' + escapeHtml(d.created_at) + '</small>';
    if (d.processing_time_display) head += '<small class="text-white-50" title="Temps de traitement"><i class="fas fa-stopwatch"></i> ' + escapeHtml(d.processing_time_display) + '</small>';
    head += '<button type="button" class="btn btn-sm btn-link text-white-50 p-0 ms-auto wama-info-deselect" title="Fermer la sélection"><i class="fas fa-xmark"></i></button>';
    head += '</div>';

    // ── ENTRÉE : fichier source + durée + propriétés ──────────────────────────
    var srcLine = '';
    if (d.source_file) {
      var fn = _basename(d.source_file);
      srcLine = '<div class="small text-truncate mb-1" title="' + escapeHtml(d.source_file) + '"><i class="fas fa-file text-info"></i> ' + escapeHtml(fn) + '</div>';
    }
    var inChips = [];
    if (d.source_duration_display) inChips.push(_detailChip(DETAIL_META.source_duration_display.icon, d.source_duration_display, DETAIL_META.source_duration_display.label));
    if (d.source_properties) inChips.push(_detailChip(d.source_properties_icon || 'fa-circle-info', d.source_properties, 'Propriétés'));
    var secIn = _section('Entrée', srcLine + _chipRow(inChips));

    // ── RÉGLAGES : moteur(s) + extras déclarés par l'app ─────────────────────
    var regChips = [];
    ['engine', 'engine_effective'].forEach(function (k) {
      if (d[k]) regChips.push(_detailChip(DETAIL_META[k].icon, d[k], DETAIL_META[k].label));
    });
    if (d.extra) Object.keys(d.extra).forEach(function (lbl) { regChips.push(_detailChip('fa-sliders', d.extra[lbl], lbl)); });
    var secReg = _section('Réglages', _chipRow(regChips));

    // ── SORTIE : format/qualité + fichier résultat ; l'ERREUR remplace (§11) ──
    var secOut;
    if (d.error_message) {
      secOut = _section('Sortie', '<div class="small text-danger"><i class="fas fa-triangle-exclamation"></i> ' + escapeHtml(d.error_message) + '</div>');
    } else {
      var outChips = [];
      ['output_format', 'output_quality'].forEach(function (k) {
        if (d[k]) outChips.push(_detailChip(DETAIL_META[k].icon, d[k], DETAIL_META[k].label));
      });
      if (d.result_file) { var rf = _basename(d.result_file); outChips.push('<a class="wama-chip" href="' + d.result_file + '" title="Résultat"><i class="fas fa-download"></i> ' + escapeHtml(rf) + '</a>'); }
      secOut = _section('Sortie', _chipRow(outChips));
    }
    return head + secIn + secReg + secOut + _ragChip(d, ctx);
  }

  // ── « Ajouter au RAG » — le GESTE, générique (WAMA_MEMORY.md §7ter, jalon 14) ─────────
  // Vit ICI et non dans les gabarits d'app : l'inspecteur est global et déjà nourri par
  // `detail_registry`, donc les 10 apps (et les suivantes) obtiennent le geste sans une ligne.
  // DATA-GATED : pas de texte dans le schéma canonique ⇒ pas de bouton. Une vidéo ou une image
  // sans sortie textuelle n'affiche rien plutôt qu'un bouton qui échouerait au clic.
  // ⚠ L'entrée au RAG est un GESTE EXPLICITE : ce bouton ne s'auto-déclenche JAMAIS, et il n'a
  // pas d'équivalent « tout ajouter » — c'est la décision de conception du 21/08, pas un manque.
  function _ragChip(d, ctx) {
    if (!ctx || !ctx.app || !ctx.pk) return '';
    var origine = d.result_text ? 'la sortie' : (d.source_text ? "l'entrée" : '');
    if (!origine) return '';
    return '<div class="wai-sec wama-rag-geste">'
      + '<button type="button" class="btn btn-sm btn-outline-success wama-rag-add"'
      + ' data-app="' + escapeHtml(ctx.app) + '" data-pk="' + escapeHtml(ctx.pk) + '"'
      + ' title="Indexer ' + origine + ' de cet élément pour que l\'IA puisse s\'en servir">'
      + '<i class="fas fa-book-open-reader"></i> Ajouter au RAG</button>'
      + '<span class="wama-rag-etat small text-white-50 ms-2"></span></div>';
  }

  function _cookie(nom) {
    var m = ('; ' + document.cookie).split('; ' + nom + '=');
    return m.length === 2 ? m.pop().split(';').shift() : '';
  }

  // Câble le bouton. Le niveau n'est PAS demandé ici : il vient du défaut de profil (page
  // « Mon RAG »). Demander le niveau à chaque clic ferait payer un arbitrage à chaque geste,
  // alors que le cas courant est « toujours le même niveau » ; le changer reste possible
  // depuis la page de gestion, où l'on voit ce qu'on a déjà partagé.
  function _wireRag(host) {
    var btn = host && host.querySelector('.wama-rag-add');
    if (!btn) return;
    var etat = host.querySelector('.wama-rag-etat');
    btn.addEventListener('click', function () {
      btn.disabled = true;
      if (etat) etat.textContent = 'Indexation…';
      var fd = new FormData();
      fd.append('app', btn.dataset.app);
      fd.append('pk', btn.dataset.pk);
      fetch('/common/api/rag/ajouter/', {
        method: 'POST', body: fd, headers: { 'X-CSRFToken': _cookie('csrftoken') },
      }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          if (!res.ok || res.j.erreur) {
            btn.disabled = false;
            if (etat) etat.textContent = res.j.erreur || 'échec';
            return;
          }
          // « en attente de vectorisation » est dit, pas tu : sans embedding le document ne
          // remonte pas encore au rappel sémantique — laisser croire l'inverse serait un
          // mensonge d'interface (les vecteurs se calculent par lot, cf. store.reindex).
          btn.innerHTML = '<i class="fas fa-check"></i> Au RAG';
          btn.classList.remove('btn-outline-success');
          btn.classList.add('btn-success');
          if (etat) {
            etat.textContent = res.j.fragments + ' fragment'
              + (res.j.fragments > 1 ? 's' : '') + ' · ' + res.j.niveau
              + ' · en attente de vectorisation';
          }
        }).catch(function () {
          btn.disabled = false;
          if (etat) etat.textContent = 'échec réseau';
        });
    });
  }

  // ── Instances COEXISTANT sur une même page ────────────────────────────────────────────
  // Les hôtes du volet sont UNIQUES par page : #inspectorInfo, #inspectorActions,
  // #info-section, #media-section, #preview-container sont lus par `document.getElementById`,
  // pas configurables. Deux instances sur la même page se les disputent donc forcément —
  // c'est le cas d'`enhancer` (image + audio) et d'`imager` (image + vidéo), qui en câblent
  // deux, une par domaine. Symptôme mesuré le 2026-08-22 : sélectionner dans un domaine puis
  // basculer sur l'autre laissait le volet peuplé par le PREMIER (actions, infos, réglages) et
  // sa card surlignée dans une file devenue invisible — deux sélections vivantes à la fois.
  //
  // Une sélection CHASSE donc les autres. Inerte par construction là où le défaut n'existe
  // pas : sur une page à instance unique le registre ne contient que l'instance courante, que
  // la boucle saute. Aucune des 14 autres instances ne change de comportement.
  //
  // ⚠ LIMITE ASSUMÉE : « même page » vaut ici « mêmes hôtes », ce qui est vrai tant que la
  // brique lit ces hôtes par id fixe. Le jour où le volet devient déclaratif et où deux
  // inspecteurs peuvent viser des hôtes DISTINCTS, il faudra les grouper par hôte plutôt que
  // par page.
  var _coexistantes = [];

  function _cederLaMain(courante) {
    _coexistantes.forEach(function (autre) {
      if (autre === courante) return;
      var s = autre.state();
      if (s.itemId !== null || s.batchId !== null) autre.deselect();
    });
  }

  function init(cfg) {
    cfg = cfg || {};
    const qc = cfg.queueContainer;
    if (!qc) return null;

    // Renseignée juste avant le `return` : les gestes de sélection ne peuvent survenir
    // qu'après, puisqu'ils naissent d'un clic de l'utilisateur.
    var api = null;

    const CARD_SEL   = cfg.cardSelector   || '.synthesis-card';
    const BATCH_SEL  = cfg.batchSelector  || '.batch-group';
    const BATCH_ATTR = cfg.batchIdAttr    || 'batchId';     // dataset key (data-batch-id)
    const HL         = cfg.highlightClass || 'inspector-selected';
    const ids = Object.assign({
      banner: 'inspectorBanner', label: 'inspectorLabel', deselect: 'inspectorDeselect',
      actions: 'inspectorActions', hint: 'inspectorActionsHint',
    }, cfg.ids || {});
    const hideOnInspect = cfg.hideOnInspect || [];
    const showOnInspect = cfg.showOnInspect || [];   // masqués tant que RIEN n'est sélectionné
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
      // Symétrique : sections qui n'ont de sens QUE pendant l'inspection (2026-08-19).
      // Sans elle, une section d'actions vide — TITRE COMPRIS — restait affichée en bas du
      // volet « aucune sélection » : le titre annonçait des actions qui n'existaient pas
      // (constaté sur model_manager, « Actions du modèle » sous un volet système).
      showOnInspect.forEach(function (id) {
        const el = $(id);
        if (el) el.style.display = inspecting ? '' : 'none';
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

    // Contraction française du préfixe : « de » + « le/les … » → « du/des … ».
    // ⚠ Les 9 apps écrivent leur libellé de lot « le batch #N » et le bandeau préfixe
    // « Réglages de » → on lisait « Réglages de le batch #2 » (relevé par Fabien le
    // 2026-08-26). Corriger les 9 libellés aurait recopié la rustine et laissé la 10ᵉ app
    // refaire la faute : une règle de LANGUE se traite une fois, au point d'assemblage.
    // Les libellés d'ÉLÉMENT (« l'élément #N ») s'élident déjà seuls et ne sont pas touchés.
    function _contracter(prefixe, libelle) {
      if (!/\bde$/i.test(prefixe)) return null;               // préfixe personnalisé : on ne touche à rien
      var m = /^(le|les)\s+(.+)$/i.exec(libelle);
      if (!m) return null;
      return { prefixe: prefixe.replace(/de$/i, m[1].toLowerCase() === 'le' ? 'du' : 'des'),
               libelle: m[2] };
    }

    function showBanner(text) {
      const b = $(ids.banner), l = $(ids.label);
      const p = document.getElementById('inspectorPrefix');
      if (p && text) {
        // Le préfixe d'origine est mémorisé : sans ça, une 2ᵉ sélection contracterait « du » → « dudu ».
        if (!p.dataset.prefixeOrigine) p.dataset.prefixeOrigine = p.textContent.trim();
        const c = _contracter(p.dataset.prefixeOrigine, text);
        p.textContent = c ? c.prefixe : p.dataset.prefixeOrigine;
        if (c) text = c.libelle;
      }
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
      // L'app et le pk ne sont PAS dans la charge utile de `unified_detail` (schéma canonique
      // figé, INSPECTOR_DETAIL_FIELDS.md) : on les lit sur l'URL qu'on vient d'appeler, qui les
      // porte par construction (`/common/detail/<app>/<pk>/`). Les ajouter au schéma aurait
      // touché les 10 adapters pour une donnée que l'appelant connaît déjà.
      var seg = durl.split('/detail/')[1] || '';
      var parts = seg.split('/').filter(Boolean);
      var ctx = parts.length >= 2 ? { app: parts[0], pk: parts[1] } : null;
      fetch(durl).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
        if (!d || d.error) { hideDetail(); return; }
        infoHost.innerHTML = renderDetailChips(d, ctx);
        _wireRag(infoHost);
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
      var lastSig = '';   // dédup : ne re-rendre que si le payload a CHANGÉ (2026-08-13) —
                          // sans ça, une URL média partielle (converter audio/webm) recréait
                          // le lecteur toutes les 1,3 s et REDÉMARRAIT la lecture. L'onde
                          // (peaks) et le texte (content) grandissent → leur signature change
                          // à chaque tick, le comportement « qui se construit » est préservé.
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
          if (!d.sides.has_during) return;
          var sig = JSON.stringify([d.url || '', d.mime_type || '',
                                    (d.peaks || []).length,
                                    (typeof d.content === 'string') ? d.content.length : -1]);
          if (sig === lastSig) return;
          lastSig = sig;
          renderInlinePreview(previewHost, d, false);
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
    // #media-section = aperçu du média, qui n'a de sens que pour un ITEM sélectionné.
    // Exceptions déclarées par l'app via keepMediaSection : certaines pages y logent un
    // contenu permanent au lieu d'un aperçu.
    //   true           → jamais masqué (contenu permanent en toutes circonstances)
    //   'no-selection' → visible HORS sélection, masqué dès qu'un item/batch est inspecté.
    //                    model_manager y place les ressources système (CPU/RAM/GPU/Disque) :
    //                    elles cèdent la place à l'inspecteur du modèle, sinon il faut
    //                    scroller tout le monitoring pour atteindre les infos du modèle.
    function setMediaSection(visible) {
      if (!mediaSection) return;
      if (cfg.keepMediaSection === 'no-selection') {
        mediaSection.style.display = visible ? 'none' : '';
        return;
      }
      if (!visible && cfg.keepMediaSection) return;
      mediaSection.style.display = visible ? '' : 'none';
    }
    function showQueueInfo() {
      setMediaSection(false);
      if (!infoHost) return;
      var c = _fileCounts();
      if (!c || !c.total) { hideDetail(); return; }
      infoHost.innerHTML = _renderAggInfo('<i class="fas fa-list text-info"></i> File · ' + c.total + ' élément' + (c.total > 1 ? 's' : ''), c);
      if (infoSection) infoSection.style.display = '';
      var banner = $(ids.banner); if (banner) banner.style.display = '';
    }
    function showBatchInfo(bid, group) {
      setMediaSection(false);
      if (!infoHost) return;
      var c = _batchCounts(group);
      infoHost.innerHTML = '<div class="d-flex align-items-center gap-2 mb-1"><strong class="text-light">Batch #' + escapeHtml(bid) + '</strong>'
        + '<button type="button" class="btn btn-sm btn-link text-white-50 p-0 ms-auto wama-info-deselect" title="Fermer la sélection"><i class="fas fa-xmark"></i></button></div>'
        + _renderAggInfo('<i class="fas fa-layer-group text-info"></i> ' + c.total + ' élément' + (c.total > 1 ? 's' : ''), c);
      if (infoSection) infoSection.style.display = '';
      var banner = $(ids.banner); if (banner) banner.style.display = 'none';
      var db = infoHost.querySelector('.wama-info-deselect');
      // ✕ → `deselect` EN DIRECT, comme le ✕ du chemin ITEM (fillDetail, plus haut).
      // Ce chemin proxifiait encore par le bouton du bandeau (`$(ids.deselect).click()`),
      // reliquat d'avant le 2026-07-08 : ce jour-là la mini-card « Réglages de l'élément #N »
      // a été RETIRÉE des apps portées au détail (PROJECT_STATUS §21.3.6) et le chemin item
      // est passé à l'appel direct — le chemin BATCH a été oublié. Conséquence mesurée le
      // 2026-08-22 : sans bandeau dans la page, `od` vaut null et le clic ne faisait RIEN
      // sur 7 pages (anonymizer, composer, converter, describer, enhancer, reader,
      // transcriber) ; seul Échap désélectionnait. Le proxy n'avait aucune vertu propre —
      // sur les pages AVEC bandeau il déclenchait ce même `deselect` (écouteur posé plus bas),
      // et `showBatchInfo` masque le bandeau juste au-dessus.
      if (db) db.addEventListener('click', deselect);
    }

    // ══ SÉLECTION MULTIPLE (Ctrl / Maj) ═══════════════════════════════════════════════════
    //
    // UNE SEULE sélection dans WAMA (arbitrage Fabien, 2026-09-04) : celle du drag&drop EST
    // celle de l'inspecteur. Le clic simple garde donc exactement son comportement d'avant
    // (1 card → détail) ; Ctrl/Maj l'étendent, et le volet bascule ici.
    //
    // ⚠ L'inspecteur ne DÉCIDE pas de la sélection, il la SUIT : `wama-queue-dnd.js` émet
    // `wama:selection-change`, ici on ne fait que rendre. Deux briques qui décideraient
    // chacune de « ce qui est sélectionné » finiraient par ne pas être d'accord — et c'est
    // l'écran qui trancherait, au hasard de l'ordre des écouteurs.
    //
    // Ce qu'on affiche est délibérément MAIGRE : combien, et les deux gestes de composition
    // (former un lot / sortir du lot). Pas de réglages — appliquer des réglages à N éléments
    // hétérogènes est une autre question (héritage batch→item, conventions §9.9), et la
    // trancher au passage aurait été la trancher mal.
    function showMultiInfo(cards) {
      setMediaSection(false);
      if (!infoHost) return;
      itemId = null; batchId = null;
      clearHighlight();
      // ⚠ Le volet RÉGLAGES doit lâcher les valeurs du dernier élément inspecté. Sans ça il
      // continue d'afficher « Paramètres de l'élément » avec le moteur, les mots-clés et les
      // interrupteurs d'UNE card pendant que N sont sélectionnées — un volet qui ment sur ce
      // qu'il édite, et dont un Enregistrer aurait écrit on ne sait où. Vu à la capture du
      // smoke, pas au code.
      if (defaults && panel.apply) panel.apply(defaults);
      var n = cards.length;
      var dansLot = cards.filter(function (c) { return !!c.closest('.batch-group'); }).length;
      var q = cards[0] && cards[0].closest('[data-wama-dnd]');
      var d = q ? q.dataset : {};
      var actions = '';
      // Un bouton n'apparaît que si la route existe ET que le geste a un sens ici : proposer
      // « sortir du lot » quand rien n'est dans un lot est un bouton mort de plus.
      if (d.dndMergeUrl && n > 1) {
        actions += '<button type="button" class="btn btn-sm btn-outline-info wama-multi-group">'
                 + '<i class="fas fa-layer-group"></i> Former un lot</button>';
      }
      if (d.dndRemoveUrl && dansLot) {
        actions += '<button type="button" class="btn btn-sm btn-outline-secondary wama-multi-ungroup">'
                 + '<i class="fas fa-object-ungroup"></i> Sortir du lot (' + dansLot + ')</button>';
      }
      infoHost.innerHTML =
        '<div class="d-flex align-items-center gap-2 mb-2">'
        + '<strong class="text-light"><i class="fas fa-check-double text-info"></i> '
        + n + ' éléments sélectionnés</strong>'
        + '<button type="button" class="btn btn-sm btn-link text-white-50 p-0 ms-auto wama-info-deselect"'
        + ' title="Fermer la sélection"><i class="fas fa-xmark"></i></button></div>'
        + (actions ? '<div class="d-flex flex-wrap gap-1">' + actions + '</div>' : '')
        + '<div class="small text-white-50 mt-2">Glissez la sélection sur une card pour former '
        + 'un lot, ou entre deux cards pour la déplacer.</div>';
      if (infoSection) infoSection.style.display = '';
      var banner = $(ids.banner); if (banner) banner.style.display = 'none';
      var db = infoHost.querySelector('.wama-info-deselect');
      if (db) db.addEventListener('click', function () {
        if (global.WamaQueueDnd) WamaQueueDnd.clear(q);
        deselect();
      });
      var g = infoHost.querySelector('.wama-multi-group');
      if (g) g.addEventListener('click', function () { _multiGrouper(cards, d); });
      var u = infoHost.querySelector('.wama-multi-ungroup');
      if (u) u.addEventListener('click', function () { _multiSortir(cards, d); });
      toggleSections(true);
      // ⚠ …puis on REND son titre neutre au volet Réglages. `toggleSections(true)` pose le
      // libellé d'inspection (« Paramètres de l'ÉLÉMENT »), juste pour un item ou un lot,
      // faux pour une sélection multiple : les valeurs affichées sont les défauts, plus
      // celles d'aucune card en particulier. Titre et contenu doivent dire la même chose —
      // c'est un titre qui ment qui rend un volet dangereux, pas un volet vide.
      if (cfg.settingsTitleSelector) {
        var t = document.querySelector(cfg.settingsTitleSelector);
        if (t && t.dataset.orig) t.innerHTML = t.dataset.orig;
      }
    }

    function _csrf() { var m = document.cookie.match(/csrftoken=([^;]+)/); return m ? m[1] : ''; }

    function _multiGrouper(cards, d) {
      var fd = new FormData();
      cards.forEach(function (c) { fd.append('ids', c.dataset.id); });
      fetch(d.dndMergeUrl, { method: 'POST', headers: { 'X-CSRFToken': _csrf() }, body: fd })
        .then(function (r) { return r.json().catch(function () { return {}; }); })
        .then(function (res) {
          if (res && res.consolidated) { location.reload(); return; }
          var msg = res && res.reason ? res.reason : 'ces éléments ne peuvent pas former un lot';
          if (global.WamaApp && WamaApp.toast) WamaApp.toast('Lot impossible — ' + msg, 'error');
          else alert('Lot impossible — ' + msg);
        });
    }

    function _multiSortir(cards, d) {
      // Séquentiel : chaque sortie recalcule le lot d'origine (et peut le supprimer).
      var aSortir = cards.filter(function (c) { return !!c.closest('.batch-group'); });
      aSortir.reduce(function (p, c) {
        return p.then(function () {
          return fetch(d.dndRemoveUrl.replace(/\/0\/?$/, '/' + c.dataset.id + '/'),
                       { method: 'POST', headers: { 'X-CSRFToken': _csrf() } });
        });
      }, Promise.resolve()).then(function () { location.reload(); });
    }

    function selectItem(id) {
      const card = qc.querySelector(CARD_SEL + '[data-id="' + id + '"]');
      if (!card) return;
      // APRÈS le garde : une sélection qui échoue ne doit pas défaire celle d'à côté.
      _cederLaMain(api);
      snapshotDefaults();
      itemId = id; batchId = null;
      clearHighlight(); card.classList.add(HL);
      if (panel.apply && cfg.cardSettings) panel.apply(cfg.cardSettings(card));
      fillActions(cfg.renderItemActions, card);
      fillPreview(card, 'Aperçu');
      setMediaSection(true);
      fillDetail(card);
      toggleSections(true);
      showBanner(itemLabel(id));
    }

    function selectBatch(bid) {
      const group = qc.querySelector(BATCH_SEL + '[data-batch-id="' + bid + '"]');
      if (!group) return;
      _cederLaMain(api);                       // cf. selectItem
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
      // Pendant contraire de renderItemActions : l'app remet SON volet à l'état
      // « aucune sélection » (invite, boutons d'action…). Indispensable parce que
      // la désélection a PLUSIEURS chemins — clic sur la croix, touche Échap,
      // clic hors card. Une app qui ne branchait que le clic laissait le volet
      // dans un état bâtard après Échap (constaté sur model_manager).
      if (cfg.onDeselect) { try { cfg.onDeselect(); } catch (e) { console.warn('onDeselect:', e); } }
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

    // La sélection multiple est ANNONCÉE par `wama-queue-dnd.js`, jamais décidée ici.
    // 0 ou 1 élément → on laisse le chemin d'avant faire son travail (`deselect`/`selectItem`
    // ont déjà été appelés par le clic) ; ≥ 2 → le volet passe en vue de sélection.
    qc.addEventListener('wama:selection-change', function (e) {
      const sel = (e.detail && e.detail.cards) || [];
      if (sel.length >= 2) showMultiInfo(sel);
      else if (!sel.length && !itemId && !batchId) deselect();
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

    // État INITIAL du volet : rien n'est sélectionné au chargement. Sans cet appel, les
    // sections `showOnInspect` restaient visibles jusqu'à la première sélection/désélection
    // — exactement le symptôme corrigé (une section d'actions vide affichée d'entrée).
    try { toggleSections(false); } catch (e) {}
    try { showQueueInfo(); } catch (e) {}
    document.addEventListener('media:processed', function () {
      if (itemId == null && batchId == null) { try { showQueueInfo(); } catch (e) {} }
    });
    // Première arrivée des compteurs (wama-global-progress) : au chargement, l'appel
    // ci-dessus court AVANT le premier poll — WamaQueueStats est indéfini et le résumé
    // « File · N éléments » restait invisible jusqu'à la première désélection (constat
    // Fabien 02/09, converter_01 — mais la course existe sur toutes les pages à file).
    document.addEventListener('wama:queue-stats', function () {
      if (itemId == null && batchId == null) { try { showQueueInfo(); } catch (e) {} }
    });

    api = {
      selectItem: selectItem,
      selectBatch: selectBatch,
      deselect: deselect,
      save: save,
      state: function () { return { itemId: itemId, batchId: batchId }; },
    };
    _coexistantes.push(api);
    return api;
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

    const cardSettings = cfg.cardSettings || function (card) { return gearValues(card, names); };

    // Sources d'options du VOLET (route F4b, 2026-09-02) : un select de volet rendu SERVEUR
    // reçoit lui aussi ses options du catalogue (+ « auto » et sa prévision si le schéma
    // déclare options_auto). Seule la source `catalog` est liée ici : les voix du volet
    // restent rendues serveur (optgroups clonés par le JS d'app — « NON remplacés »).
    // Sans cet appel, seules les modales (rendues par WamaParams.render) passaient par les
    // sources d'options — mesuré sur /synthesizer/ : le select du volet gardait sa liste
    // serveur pendant que la modale servait « auto ».
    if (WP && WP.bindOptionSources) {
      WP.bindOptionSources(ph || document, schema, 'panel',
        function (p) { return p.options_source === 'catalog'; });
    }

    return init(Object.assign({}, cfg, { panel: panel, cardSettings: cardSettings }));
  }

  // ── Preview de RÉSULTAT dans les CARDS — mécanisme COMMUN (18/08, décision Fabien) ─────
  // La route (mécanisme « Preview unifiée » n°30) veut que la preview vienne du COMMUN, pas
  // d'un markup par app : une card déclare UNIQUEMENT un placeholder
  //   <div class="wcv3-preview" data-card-preview="<unified_preview>?side=output"
  //        data-player-id="<pk>"></div>
  // et l'hydrateur ci-dessous fetch le JSON unified_preview puis rend via le MÊME
  // renderInlinePreview que le volet (mime-driven : image/vidéo/audio-waveform+pics/pdf/
  // texte). Remplace les markups <video>/<img> écrits à la main dans les templates.
  function hydrateCardPreviews(root) {
    var scope = root || document;
    var hosts = scope.querySelectorAll('[data-card-preview]:not([data-preview-hydrated])');
    hosts.forEach(function (host) {
      host.setAttribute('data-preview-hydrated', '1');
      fetch(host.getAttribute('data-card-preview'))
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (d && (d.url || typeof d.content === 'string')) renderInlinePreview(host, d, false);
        })
        .catch(function () { /* best-effort : la card reste lisible sans preview */ });
    });
  }
  // Auto : au chargement + sur toute mutation de la page (refreshCard remplace des nœuds,
  // les batchs se déplient…). Observer léger : ne re-scanne que si des nœuds sont AJOUTÉS.
  //
  // ⚠ Le déclencheur regarde si les nœuds AJOUTÉS portent (ou contiennent) un hôte de preview,
  // au lieu de re-scanner tout le document à chaque lot. Sans ce filtre, ce fichier ne pouvait
  // pas être chargé globalement : sur une page à fort brassage DOM et SANS card (filemanager et
  // son arbre jstree, polling des stats), chaque ajout de nœud déclenchait un
  // `querySelectorAll` sur tout le document, pour rien. Le comportement est inchangé là où il
  // y a des cards — on ne fait que cesser de payer là où il n'y en a pas. (2026-08-20, préalable
  // au chargement global demandé par Fabien.)
  var HOTE_PREVIEW = '[data-card-preview]';
  function _contientHote(n) {
    if (!n || n.nodeType !== 1) return false;
    return (n.matches && n.matches(HOTE_PREVIEW)) ||
           (n.querySelector && !!n.querySelector(HOTE_PREVIEW));
  }
  document.addEventListener('DOMContentLoaded', function () {
    hydrateCardPreviews(document);
    try {
      new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
          var ajouts = muts[i].addedNodes;
          for (var j = 0; ajouts && j < ajouts.length; j++) {
            if (_contientHote(ajouts[j])) { hydrateCardPreviews(document); return; }
          }
        }
      }).observe(document.body, { childList: true, subtree: true });
    } catch (e) { /* très vieux navigateur : hydratation au chargement seulement */ }
  });

  // ── Lecture des réglages d'une card depuis ses data-* — LE lecteur unique ──────────────
  // Extrait de la closure d'initFromSchema le 2026-09-02, parce qu'un second consommateur est
  // né (la modale de LOT pré-remplie) : deux lecteurs auraient re-divergé, c'est le motif
  // « deux lecteurs, deux sources » que la session du 30/08 a déjà payé (modale vs volet).
  // Les data-* peuvent être sur la RACINE de card OU sur le bouton ⚙ (cas le plus courant).
  // UNE seule graphie depuis le 2026-08-23 : `.settings-btn` (contrat queue-actions, porté par
  // les 10 apps) ; `[data-action="settings"]` GARDÉ — enhancer et reader le portent en plus,
  // et il dit l'INTENTION indépendamment du nommage.
  function gearValues(card, names) {
    const out = {};
    const btn = card.querySelector('.settings-btn, [data-action="settings"]');
    const datasets = btn ? [card.dataset, btn.dataset] : [card.dataset];
    (names || []).forEach(function (n) {
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
  }

  // Valeurs PARTAGÉES par toutes les filles d'un lot — la sémantique de la carte MÈRE
  // (« valeur si partagée par toutes »), appliquée à la modale de LOT (2026-09-02, constat
  // Fabien : la modale s'ouvrait toujours sur « — inchangé — », comme si rien n'était
  // enregistré — or un lot n'a PAS d'état propre, ses réglages vivent sur les filles ; le
  // pré-remplissage juste est donc l'intersection, et « inchangé » ne reste que là où les
  // filles DIVERGENT réellement).
  function sharedGearValues(groupEl, names) {
    // ⚠ Sélecteur STRICT (racines de card, mère exclue) : un `[data-id]` nu attrapait aussi
    // les BOUTONS d'action des filles — leur gearValues rend {}, et {} en intersection
    // annule TOUT (mesuré le 02/09 : modale de lot toujours vide malgré des filles unanimes).
    const cards = groupEl
      ? groupEl.querySelectorAll('.wama-card[data-id]:not(.is-batch), .job-card[data-id]:not(.is-batch)')
      : [];
    let commun = null;
    cards.forEach(function (card) {
      const v = gearValues(card, names);
      if (commun === null) { commun = v; return; }
      Object.keys(commun).forEach(function (k) {
        if (String(commun[k]) !== String(v[k])) delete commun[k];
      });
    });
    return commun || {};
  }

  global.WamaInspector = { init: init, initFromSchema: initFromSchema, cloneActions: cloneActions,
                           cloneBatchActions: cloneBatchActions,
                           renderInlinePreview: renderInlinePreview,
                           gearValues: gearValues, sharedGearValues: sharedGearValues,
                           hydrateCardPreviews: hydrateCardPreviews };
})(window);
