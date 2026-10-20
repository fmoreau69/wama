document.addEventListener('DOMContentLoaded', function () {
  const config = window.ENHANCER_APP || {};
  const csrfToken = config.csrfToken;
  const queueTable = document.getElementById('enhancer-queue');

  // Délégué à WamaApp (brique commune wama-app-base.js) ; repli local si non chargé.
  function getUrl(template, id) {
    return window.WamaApp ? WamaApp.getUrl(template, id) : template.replace('/0/', `/${id}/`);
  }

  function csrfHeaders(extra = {}) {
    return Object.assign({}, extra, {
      'X-CSRFToken': csrfToken,
    });
  }

  // ── Voie d'import (IMAGE/VIDÉO) : brique commune WamaImport — portage 2026-09-07 ──
  //
  // 5ᵉ app EN PLACE à l'adopter (plan « fichiers d'entrée », MEDIA_STORAGE_TIERING §8 ;
  // inventaire ROUTE §Portage F2). Ce qui vivait ici — `uploadFile`, `handleFiles` (lot testé
  // sur CHAQUE fichier), `initUpload`, `initDragDrop` (clic, survol, drop récursif, sélecteur de
  // dossier, bouton « parcourir » que la card commune ne rend pas) — est le contrat de la brique.
  // L'app ne DÉCLARE que :
  //   • `batchScope:'each'` : chaque fichier est testé comme descripteur de lot (évolution 6) ;
  //   • `extraFields`     : format et qualité de sortie du volet ;
  //   • `afterImport`     : SA politique d'affichage — 1 élément → la card arrive RENDUE DU
  //                         SERVEUR en tête de file (`appendRow`, sans reload) ; plusieurs →
  //                         reload (la consolidation vient d'être faite par la brique).
  //                         L'ancienne boucle insérait chaque card PUIS rechargeait quand N > 1 :
  //                         des insertions aussitôt effacées. Réponse brute reçue via
  //                         `reponses` (évolution 7).
  // ⚠ La voie AUDIO (`audio-enhancer.js`, zone `dropZoneAudio`) n'est PAS concernée : lot maison
  // (`AUDIO_BATCH_EXTS`, `batch_file`) hors `WamaBatchImport` — inventaire ROUTE : « ❌ sans
  // évolution ». Deux voies sur la même page, une seule portée ici.
  function initImport() {
    if (typeof window.WamaImport !== 'function') {
      // Défaut le plus silencieux qui soit (une zone de dépôt que rien n'écoute) → on le DIT.
      WamaApp.toast("Voie d'import non chargée (wama-import.js) — dépôt impossible", 'error');
      console.error('[Enhancer] WamaImport absent : wama-import.js non chargé par le gabarit');
      return;
    }
    window._import = WamaImport({
      uploadUrl:        config.uploadUrl,
      consolidateUrl:   config.consolidateUrl,
      consolidateField: 'ids',
      csrfToken:        csrfToken,
      dropZoneId:       'dropZoneEnhancer',
      fileInputId:      'enhancer-file',
      folderInputId:    'enhancerFolderInput',
      batch:            window._batchImport,
      batchScope:       'each',
      extraFields:      function (fd) {
        fd.append('output_format', (document.getElementById('output_format') || {}).value || 'original');
        fd.append('output_quality', (document.getElementById('output_quality') || {}).value || 'balanced');
        // « Garder la résolution d'origine » (2026-10-16) : appliqué au process « Sortie ».
        const keepSize = document.getElementById('outputKeepSize');
        if (keepSize) fd.append('output_keep_size', keepSize.checked ? 'true' : 'false');
        // Tirage auto : facteur + curseur du volet voyagent avec le dépôt (curseur C, 21/09).
        const auto = panelAutoValues();
        fd.append('upscale_factor', auto.upscale_factor);
        fd.append('quality_intent', auto.quality_intent);
        // Modèle, débruitage, blend du volet (2026-09-29) : ils ne partaient qu'avec « Tout
        // démarrer » — l'élément naissait sur les défauts. Il naît désormais COMPLET, et le
        // serveur MÉMORISE ce que le volet poste (brique commune `save_panel_settings`).
        const model = document.getElementById('defaultAiModel');
        const denoise = document.getElementById('defaultDenoise');
        const blend = document.getElementById('defaultBlendFactor');
        if (model && model.value) fd.append('ai_model', model.value);
        if (denoise) fd.append('denoise', denoise.checked ? 'true' : 'false');
        if (blend) fd.append('blend_factor', blend.value);
      },
      afterImport:      function (ids, reponses) {
        if (ids.length !== 1) { location.reload(); return; }
        const data = reponses[0] || { id: ids[0] };
        data.status = data.status || 'PENDING';
        appendRow(data);
      },
    });
  }

  async function refreshCard(id) {
    // Card = partial SERVEUR unique, REDEMANDÉE par la brique commune (WamaApp.fetchCard,
    // portage 2026-09-21 — la copie locale du fetch vivait ici) ; les événements de la
    // file sont délégués (document/bindRowActions sur la card fraîche).
    const fresh = await WamaApp.fetchCard(config.cardHtmlUrlTemplate, id);
    const existing = queueTable ? queueTable.querySelector(`[data-id="${id}"]`) : null;
    if (fresh && existing) {
      existing.replaceWith(fresh);
      bindRowActions(fresh);
      if (typeof initMediaPreview === 'function') initMediaPreview();
    }
    return fresh;
  }

  async function appendRow(data) {
    if (!queueTable) return;

    // Card = rendu SERVEUR (plus de markup construit côté JS), par la brique commune.
    const card = await WamaApp.fetchCard(config.cardHtmlUrlTemplate, data.id);
    if (!card) {
      location.reload();   // repli : le rechargement rend les cards serveur
      return;
    }
    queueTable.prepend(card);
    bindRowActions(card);

    if (typeof initMediaPreview === 'function') {
      initMediaPreview();
    }
  }

  // ⚙ item : le CYCLE complet (rendre du schéma → greffer le pied → afficher → lire →
  // enregistrer → enchaîner) est la brique commune `WamaParams.settingsModal` (portage
  // 2026-09-21 — `createSettingsModal` + `handleSaveSettings` le recopiaient ici). Les VALEURS
  // viennent des data-* du gear (brique `card_gear`), lues par LE lecteur unique
  // `WamaInspector.gearValues` (revérification 21/09 : une copie locale vivait ici).
  function openSettingsModal(id, btn) {
    const schema = window.ENHANCER_MEDIA_SCHEMA || [];
    const card = (btn && btn.closest('.wama-card')) || btn;
    return WamaParams.settingsModal({
      id: id,
      title: 'Paramètres - #' + id,
      titleIcon: 'fa-magic',
      schema: schema,
      values: WamaInspector.gearValues(card, schema.map(function (p) { return p.name; })),
      formClass: 'enhancement-settings-form',
      footerTplId: 'mediaSettingsFooterTpl',
      saveUrl: getUrl(config.updateSettingsUrlTemplate, id),
      csrf: csrfToken,
      onSaved: function (gid, restart) {
        // La card reflète les réglages enregistrés (chips, gear) ; « Sauvegarder et
        // relancer » lance ensuite avec les valeurs STOCKÉES (le geste vaut confirmation).
        refreshCard(gid).then(function () {
          if (restart) handleRestartEnhancement(gid, { confirmed: true });
        });
      },
    });
  }

  // Polling : brique commune WamaApp.Poller (résilient : retries maxFails ; jamais deux requêtes en
  // vol, pause en onglet caché). Sa copie locale « de repli si WamaApp absent » est retirée le
  // 2026-10-13 : la brique est montée par `base.html` sur toutes les pages, le repli ne servait
  // jamais — et c'est sa `Map` que « Tout effacer » parcourait, vide : rien n'était arrêté.
  const poller = new WamaApp.Poller({
    urlTemplate: config.progressUrlTemplate,
    onData: function (id, data) { updateRow(id, data); },
    interval: 1500,
  });

  function startPolling(id) { poller.start(id); }

  function stopPolling(id) { poller.stop(id); }

  async function updateRow(id, data) {
    const card = queueTable ? queueTable.querySelector(`[data-id="${id}"]`) : null;
    if (!card) {
      stopPolling(id);
      return;
    }

    const progress = Math.min(100, Math.max(0, data.progress || 0));
    const status = (data.status || 'PENDING').toUpperCase();

    if (window.WamaEta) WamaEta.render(card.querySelector('.wama-eta'), WamaEta.update(id, { progress: progress, status: status, seedSeconds: data.estimated_seconds, modelLoaded: false }));

    if (status === (card.dataset.status || '').toUpperCase()) {
      // Même état : maj légère de la progression (markup = brique _card_progress).
      const fill = card.querySelector('.wama-progress-fill');
      if (fill) fill.style.width = `${progress}%`;
      const progressText = card.querySelector('.progress-text');
      if (progressText) progressText.textContent = `${progress}%`;
    } else {
      // Transition d'état → re-rendu SERVEUR de la card (source unique du markup).
      await refreshCard(id);
    }

    if (status === 'SUCCESS') {
      stopPolling(id);
    } else if (status === 'FAILURE' || progress >= 100) {
      stopPolling(id);
    }

  }

  // ⏹ Stop : arrête l'amélioration image/vidéo → item relançable (↻ via autoSync sur data-status).
  function handleStopEnhancement(id) {
    if (!id) return;
    fetch(`/enhancer/stop/${id}/`, { method: 'POST', headers: csrfHeaders() })
      .then(r => r.json())
      .then(data => {
        const card = queueTable ? queueTable.querySelector(`[data-id="${id}"]`) : null;
        if (card && data.status) card.dataset.status = data.status;
        stopPolling(id);
        // Re-rendu SERVEUR : sans lui la card restait visuellement « en cours » jusqu'au F5
        // (même défaut que l'avatarizer, corrigé en famille — constat Fabien 17/08).
        refreshCard(id);
      })
      .catch(() => {});
  }

  // Bouton de cycle commun ▶/⏹/↻ (image/vidéo) : wire délégué + auto-sync sur data-status.
  if (window.WamaCycleButton && queueTable) {
    // ▶ d'UN process (bande des process, `data-process`) : route `start/<id>/<process>/`.
    WamaCycleButton.wire(queueTable, {
      start: (id, btn) => handleRestartEnhancement(id, { process: WamaCycleButton.processOf(btn) }),
      stop: (id) => handleStopEnhancement(id),
    });
    WamaCycleButton.autoSync({ container: queueTable, cardSelector: '.synthesis-card' });
  }

  function handleRestartEnhancement(id, opts) {
    if (!id) return;

    const card = queueTable ? queueTable.querySelector(`[data-id="${id}"]`) : null;
    if (!card) return;

    const status = (card.dataset.status || '').toUpperCase();
    if (!(opts && opts.confirmed) && (status === 'SUCCESS' || status === 'RUNNING')) {
      if (!confirm('Relancer le traitement de ce fichier ?')) {
        return;
      }
    }

    // Corps VIDE : le lancement lit les réglages STOCKÉS de l'item (modale/volet écrivent
    // AVANT — modèle événementiel ; l'ancien corps relisait le formulaire d'une modale maison).
    fetch(WamaCycleButton.processUrl(getUrl(config.startUrlTemplate, id), opts && opts.process), {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({}),
    })
      .then((response) => {
        if (!response.ok) {
          return response.json().then((err) => {
            throw new Error(err.error || err.message || 'Erreur serveur');
          });
        }
        return response.json();
      })
      .then(() => {
        updateRow(id, { status: 'RUNNING', progress: 0 });
        startPolling(id);
      })
      .catch((error) => {
        console.error('Erreur restart:', error);
        WamaApp.toast(error.message || 'Erreur lors du démarrage du traitement.', 'error');
      });
  }

  function bindRowActions(scope) {
    // 🗑 : plus de bind ici — brique commune queue-actions.js sur `.delete-btn[data-delete-url]`
    // (portage 2026-08-23 ; l'attribut était déjà posé, seule la classe manquait).

    const restartButtons = (scope || document).querySelectorAll('.js-restart-enhancement');
    restartButtons.forEach((btn) => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => handleRestartEnhancement(btn.dataset.id));
    });

    // ⚙ : plus de bind ici non plus — l'ouvreur est déclaré UNE fois à la brique (voir plus bas) ;
    // les boutons du pied de modale sont délégués par le cycle commun (WamaParams.settingsModal).
  }

  // ⚙ item (card AMÉLIORATION) — ouvreur DÉCLARÉ à la brique commune (queue-actions.js).
  // Sans `within` : c'est l'ouvreur par DÉFAUT de la page. Les cards AUDIO, qui vivent dans
  // `#audio-enhancer-queue`, déclarent le leur avec un `within` (audio-enhancer.js) et sont donc
  // évaluées en premier — deux familles de cards dans une même app, sans une ligne d'app dans la
  // brique (portage 2026-08-23).
  WamaQueueActions.onSettings(function (id, btn) { openSettingsModal(id, btn); });

  // 🗑 RÉSIDU de suppression (cards AMÉLIORATION) — la brique fait le reste. Pas de `within` :
  // c'est le résidu par DÉFAUT de la page, celui des cards audio étant scopé (audio-enhancer.js).
  WamaQueueActions.onDeleted(function (id) {
    stopPolling(id);
  });

  // ── Volet : réglages du tirage « auto » (facteur + curseur) ──
  // Visibles sur « auto » seulement : depuis que le volet est GÉNÉRÉ (2026-10-11), c'est le
  // `show_if` du schéma qui les montre — la bascule écrite ici (`#mediaAutoOptions`) est partie.
  function panelAutoValues() {
    // Ce que le volet dit du tirage auto — posté avec les autres défauts du volet.
    return {
      upscale_factor: document.getElementById('mediaUpscaleFactor')?.value || '4',
      quality_intent: document.getElementById('mediaQualityIntent')?.value || '',
    };
  }

  function initExistingRows() {
    if (!queueTable) return;
    queueTable.querySelectorAll('[data-id]').forEach((card) => {
      const id = card.dataset.id;
      const status = (card.dataset.status || '').toUpperCase();
      bindRowActions(card);
      if (['PENDING', 'RUNNING', 'STARTED'].includes(status)) {
        startPolling(id);
      }
    });
  }

  // ▶ Démarrer tout et 🗑 Tout effacer : brique `queue-actions.js` (2026-10-17) — corps et suite
  // du ▶ déclarés plus bas (`onQueueStartBody` / `onQueueStarted`, domaine image_video). ⬇ Tout
  // télécharger : lien de la brique `_download_button.html`, rendu prêt par la barre globale
  // (`initBulkActions` et `updateDownloadAllState` retirés le même jour).

  // (Barre globale + ETA : brique commune wama-global-progress.js. La copie locale, neutralisée
  // par un `return` et pourtant rappelée toutes les 2 s, est retirée le 2026-10-13.)

  // === Import par URL : le FORMALISME COMMUN (2026-09-08) ===
  // Même reste de portage que l'anonymizer : ce JS postait `media_url` à la vue d'upload
  // (téléchargement À L'IMPORT, bouton bloqué le temps du transfert — d'où le skip nocturne
  // « l'app RÉSOUT l'URL à l'import »). Désormais comme les autres apps : l'URL = un lot d'une
  // ligne, `batch_create` la stocke en `source_url` (`WAMA_INGEST` sur `Enhancement`) et
  // `ensure_local_input` la télécharge AU LANCEMENT. `initUrlImport` (commun) porte champ,
  // bouton, touche Entrée, spinner, vidage et erreurs.
  function initUrlUpload() {
    if (!window.WamaApp || !WamaApp.initUrlImport) return;
    WamaApp.initUrlImport({
      inputId: 'enhancerUrlInput',
      buttonId: 'enhancerUrlSubmit',
      onEmpty: function () { WamaApp.toast('Veuillez entrer une URL de média.', 'warning'); },
      onSubmit: function (url) {
        if (!window._batchImport) throw new Error("Import batch non initialisé");
        return window._batchImport.ingestText(url + '\n', 'url.txt');
      },
    });
  }

  // « Réinitialiser » : les défauts du SCHÉMA du domaine affiché (brique commune applyDefaults,
  // comme le transcriber et le synthesizer), posés par l'applicateur de son inspecteur — il émet
  // `change`, donc les `show_if`, la prévision « auto » et l'appariement suivent. Chaque domaine
  // remettait ses champs un à un, ids et valeurs écrits ici.
  const resetBtn = document.getElementById('resetOptions');
  if (resetBtn && window.WamaParams) {
    resetBtn.addEventListener('click', () => {
      const audioSettings = document.getElementById('audioSettings');
      const audioActive = audioSettings && audioSettings.style.display !== 'none';
      const host = document.getElementById(audioActive ? 'audioPanelFields' : 'mediaPanelFields');
      const schema = audioActive ? window.ENHANCER_AUDIO_SCHEMA : window.ENHANCER_MEDIA_SCHEMA;
      const vals = WamaParams.applyDefaults(host, schema || [], 'panel');
      const panels = window._enhancerPanels || {};
      const insp = panels[audioActive ? 'audio' : 'image_video'];
      if (insp && insp.apply) insp.apply(vals);
    });
  }

  // Initialize
  initImport();
  initUrlUpload();
  initExistingRows();
  bindRowActions(document);

  // Bind actions to existing modals (loaded from Django template)
  setTimeout(() => {
    bindRowActions(document);
  }, 100);

  // ── Batch detect bar — delegated to WamaBatchImport (common/js/batch-import.js)
  // Initialisation dans le template via window._batchImport = WamaBatchImport({...})

  // ── ▶ ⧉ 🗑 de LOT : brique commune `queue-actions.js` (2026-08-27) ─────
  // Les trois handlers qui vivaient ici ont été retirés AVEC la pose de `actions_communes=True`
  // sur l'include de la file média (geste ATOMIQUE : l'un sans l'autre = double POST ou bouton
  // inerte). Ils se scopaient sur `#enhancer-queue`, un id CSS d'app ; la brique se scope sur le
  // DOMAINE déclaré (`data-domain="image_video"`, porté par l'onglet et par la card mère).
  //
  // Seule spécificité à PRÉSERVER : l'enhancer n'a jamais rechargé après un lancement de lot, il
  // insère et POLLE (famille composer/describer). C'est ce que déclare cette suite — le défaut de
  // la brique (rechargement) aurait fait perdre le suivi en direct du lot qu'on vient de lancer.
  if (window.WamaQueueActions) {
    WamaQueueActions.onBatchStarted(function (d) {
      (d.started || []).forEach(id => startPolling(id));
    }, { domain: 'image_video' });

    // ▶ de FILE (2026-10-17, ex-`handleStartAll`) — mêmes deux spécificités qu'au lot : le CORPS
    // porte les réglages par défaut du volet (la vue `start_all` les applique à tout l'élément),
    // et la SUITE polle au lieu de recharger.
    WamaQueueActions.onQueueStartBody(function () {
      return Object.assign({
        ai_model: document.getElementById('defaultAiModel')?.value,
        denoise: document.getElementById('defaultDenoise')?.checked,
        blend_factor: document.getElementById('defaultBlendFactor')?.value,
      }, panelAutoValues());
    }, { domain: 'image_video' });
    WamaQueueActions.onQueueStarted(function (data) {
      const started = data.started_ids || [];
      const errors = data.errors || [];
      if (errors.length) {
        console.error('Erreurs lors du démarrage:', errors);
        WamaApp.toast(`Certains fichiers n'ont pas pu démarrer. Vérifiez que Celery est lancé.\n${errors[0].error}`, 'error');
      }
      if (!started.length && !errors.length) WamaApp.toast('Aucun fichier à traiter.', 'warning');
      started.forEach(id => startPolling(id));
    }, { domain: 'image_video' });
  }

  // Duplication d'item : gérée par la brique commune queue-actions.js (chargée
  // globalement par base.html) — le handler local dupliquait la requête.

  // ── ⚙ Batch settings : modale BATCH commune (WamaParams context:'batch') ──
  let _batchParamsRendered = false;
  document.addEventListener('click', function(e) {
    const bs = e.target.closest('.batch-settings-btn');
    if (!bs || !bs.closest('#enhancer-queue')) return;
    const modal = document.getElementById('batchSettingsModal');
    if (!modal || !window.WamaParams) return;
    if (!_batchParamsRendered) {
      WamaParams.render(document.getElementById('enhancerBatchParams'),
                        window.ENHANCER_MEDIA_SCHEMA || [], { context: 'batch', values: {} });
      _batchParamsRendered = true;
    }
    modal.dataset.batchId = bs.dataset.batchId;
    const idBadge = document.getElementById('batchSettingsBatchId');
    if (idBadge) idBadge.textContent = '#' + bs.dataset.batchId;
    new bootstrap.Modal(modal).show();
  });

  async function saveBatchSettings(andStart) {
    const modal = document.getElementById('batchSettingsModal');
    const bid = modal && modal.dataset.batchId;
    if (!bid) return;
    const vals = WamaParams.read(document.getElementById('enhancerBatchParams'));
    const fd = new FormData();
    Object.keys(vals).forEach(k => fd.append(k, vals[k]));
    try {
      await fetch(getUrl(config.batchUpdateUrlTemplate, bid), {
        method: 'POST', headers: csrfHeaders(), body: fd,
      });
      if (andStart) {
        await fetch(getUrl(config.batchStartUrlTemplate, bid), {
          method: 'POST', headers: csrfHeaders(),
        });
      }
    } catch (err) { /* réseau */ }
    const inst = bootstrap.Modal.getInstance(modal);
    if (inst) inst.hide();
    location.reload();
  }
  document.addEventListener('click', function(e) {
    if (e.target.closest('#saveBatchSettingsBtn')) saveBatchSettings(false);
    if (e.target.closest('#saveBatchSettingsAndStartBtn')) saveBatchSettings(true);
  });

});
