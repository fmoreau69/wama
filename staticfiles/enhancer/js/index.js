document.addEventListener('DOMContentLoaded', function () {
  const config = window.ENHANCER_APP || {};
  const csrfToken = config.csrfToken;
  const queueTable = document.getElementById('enhancer-queue');
  const startProcessBtn = document.getElementById('enhancer-process-btn');
  const clearAllBtn = document.getElementById('enhancer-clear-btn');
  const downloadAllBtn = document.getElementById('enhancer-download-all-btn');

  const pollers = new Map();

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
        // Tirage auto : facteur + curseur du volet voyagent avec le dépôt (curseur C, 21/09).
        const auto = panelAutoValues();
        fd.append('upscale_factor', auto.upscale_factor);
        fd.append('quality_intent', auto.quality_intent);
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

    const empty = queueTable.querySelector('.empty-state');
    if (empty) empty.remove();

    // Card = rendu SERVEUR (plus de markup construit côté JS), par la brique commune.
    const card = await WamaApp.fetchCard(config.cardHtmlUrlTemplate, data.id);
    if (!card) {
      location.reload();   // repli : le rechargement rend les cards serveur
      return;
    }
    queueTable.prepend(card);
    bindRowActions(card);
    updateDownloadAllState();

    if (typeof initMediaPreview === 'function') {
      initMediaPreview();
    }
  }

  // ⚙ item : le CYCLE complet (rendre du schéma → greffer le pied → afficher → lire →
  // enregistrer → enchaîner) est la brique commune `WamaParams.settingsModal` (portage
  // 2026-09-21 — `createSettingsModal` + `handleSaveSettings` le recopiaient ici). Les VALEURS
  // viennent des data-* du bouton ⚙ (brique `card_gear` : tous les params de contexte item),
  // lues par le NOM du schéma — aucune liste de champs écrite dans ce fichier.
  function valuesFromGear(btn, schema) {
    const out = {};
    (schema || []).forEach(function (p) {
      const camel = p.name.replace(/_([a-z])/g, function (_, c) { return c.toUpperCase(); });
      if (btn && btn.dataset[camel] !== undefined) out[p.name] = btn.dataset[camel];
    });
    return out;
  }

  function openSettingsModal(id, btn) {
    return WamaParams.settingsModal({
      id: id,
      title: 'Paramètres - #' + id,
      titleIcon: 'fa-magic',
      schema: window.ENHANCER_MEDIA_SCHEMA || [],
      values: valuesFromGear(btn, window.ENHANCER_MEDIA_SCHEMA),
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

  // Polling délégué à WamaApp.Poller (brique commune, résilient : retries maxFails).
  // Création paresseuse (config.progressUrlTemplate prêt) ; repli local si WamaApp absent.
  let _poller = null;
  function _getPoller() {
    if (!window.WamaApp) return null;
    if (!_poller) {
      _poller = new WamaApp.Poller({
        urlTemplate: config.progressUrlTemplate,
        onData: function (id, data) { updateRow(id, data); },
        interval: 1500,
      });
    }
    return _poller;
  }

  function startPolling(id) {
    const p = _getPoller();
    if (p) { p.start(id); return; }
    if (pollers.has(id)) return;
    const interval = setInterval(() => {
      fetch(getUrl(config.progressUrlTemplate, id))
        .then((response) => response.json())
        .then((data) => updateRow(id, data))
        .catch(() => stopPolling(id));
    }, 1500);
    pollers.set(id, interval);
  }

  function stopPolling(id) {
    const p = _getPoller();
    if (p) { p.stop(id); return; }
    const interval = pollers.get(id);
    if (interval) {
      clearInterval(interval);
      pollers.delete(id);
    }
  }

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
      if (window.WamaFM) WamaFM.processed();  // sortie créée → refresh filemanager
    } else if (status === 'FAILURE' || progress >= 100) {
      stopPolling(id);
    }

    updateDownloadAllState();
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
    WamaCycleButton.wire(queueTable, { start: (id) => handleRestartEnhancement(id), stop: (id) => handleStopEnhancement(id) });
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
    fetch(getUrl(config.startUrlTemplate, id), {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({}),
    })
      .then((response) => {
        if (!response.ok) {
          return response.json().then((err) => {
            throw new Error(err.message || 'Erreur serveur');
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
    insertEmptyRowIfNeeded();
    updateDownloadAllState();
  });

  // ── Volet : réglages du tirage « auto » (facteur + curseur) visibles sur « auto » seulement ──
  // Le volet est rendu serveur (pas de show_if de schéma dessus) : une bascule d'une ligne,
  // même mécanique que le synthesizer (`intentSliderGroup`).
  function syncMediaAutoOptions() {
    const sel = document.getElementById('defaultAiModel');
    const box = document.getElementById('mediaAutoOptions');
    if (sel && box) box.hidden = (sel.value || 'auto') !== 'auto';
  }
  function panelAutoValues() {
    // Ce que le volet dit du tirage auto — posté avec les autres défauts du volet.
    return {
      upscale_factor: document.getElementById('mediaUpscaleFactor')?.value || '4',
      quality_intent: document.getElementById('mediaQualityIntent')?.value || '',
    };
  }
  (function initMediaAutoOptions() {
    const sel = document.getElementById('defaultAiModel');
    if (sel) sel.addEventListener('change', syncMediaAutoOptions);
    syncMediaAutoOptions();
  })();

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
    updateDownloadAllState();
  }

  function initBulkActions() {
    if (startProcessBtn) {
      startProcessBtn.addEventListener('click', handleStartAll);
    }
    if (clearAllBtn) {
      clearAllBtn.addEventListener('click', handleClearAll);
    }
    if (downloadAllBtn) {
      downloadAllBtn.addEventListener('click', () => {
        window.location.href = config.downloadAllUrl;
      });
    }
  }

  function handleStartAll() {
    if (!config.startAllUrl || !queueTable) return;

    // Get default settings
    const defaultAiModel = document.getElementById('defaultAiModel')?.value;
    const defaultDenoise = document.getElementById('defaultDenoise')?.checked;
    const defaultBlendFactor = document.getElementById('defaultBlendFactor')?.value;

    startProcessBtn.disabled = true;

    fetch(config.startAllUrl, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(Object.assign({
        ai_model: defaultAiModel,
        denoise: defaultDenoise,
        blend_factor: defaultBlendFactor
      }, panelAutoValues())),
    })
      .then((response) => {
        if (!response.ok) {
          return response.json().then((err) => {
            throw new Error(err.message || 'Erreur serveur');
          });
        }
        return response.json();
      })
      .then((data) => {
        const started = data.started_ids || [];
        const errors = data.errors || [];

        if (errors.length > 0) {
          console.error('Erreurs lors du démarrage:', errors);
          WamaApp.toast(`Certains fichiers n'ont pas pu démarrer. Vérifiez que Celery est lancé.\n${errors[0].error}`, 'error');
        }

        if (!started.length) {
          if (!errors.length) {
            WamaApp.toast('Aucun fichier à traiter.', 'warning');
          }
          return;
        }
        started.forEach((id) => {
          startPolling(id);
        });
      })
      .catch((error) => {
        console.error('Erreur start_all:', error);
        WamaApp.toast(error.message || 'Erreur lors du démarrage des traitements.', 'error');
      })
      .finally(() => {
        startProcessBtn.disabled = false;
      });
  }

  function handleClearAll() {
    if (!config.clearUrl || !queueTable) return;
    if (!confirm('Supprimer tous les fichiers ?')) {
      return;
    }

    clearAllBtn.disabled = true;

    fetch(config.clearUrl, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({}),
    })
      .then((response) => response.json())
      .then(() => {
        // Cards d'élément ET cards mères de lot : `[data-id]` seul laissait le lot à l'écran
        // jusqu'au rechargement. Brique commune (`wama-queue.js`), chargée par `base.html`
        // sur TOUTES les pages : appel direct, sans garde `if (window.…)` — une garde
        // rendrait muette la seule chose qu'on veut voir si elle casse.
        WamaQueue.clearCards(queueTable);
        pollers.forEach((_, id) => stopPolling(id));
        if (window.WamaFM) WamaFM.deleted();  // fichiers supprimés → refresh filemanager
        insertEmptyRowIfNeeded(true);
        updateDownloadAllState();
      })
      .catch((error) => {
        WamaApp.toast(error.message || 'Erreur lors de la suppression.', 'error');
      })
      .finally(() => {
        clearAllBtn.disabled = false;
      });
  }

  function insertEmptyRowIfNeeded(force = false) {
    if (!queueTable) return;

    const hasItems = queueTable.querySelectorAll('[data-id]').length > 0;
    const existingEmpty = queueTable.querySelector('.empty-state');

    if (!hasItems || force) {
      if (existingEmpty) return;
      const el = document.createElement('div');
      el.className = 'empty-state text-center py-4 text-white-50';
      el.textContent = 'Aucun fichier en attente.';
      queueTable.appendChild(el);
    } else if (existingEmpty) {
      existingEmpty.remove();
    }
  }

  function updateDownloadAllState() {
    if (!downloadAllBtn || !queueTable) return;
    const hasSuccess = !!queueTable.querySelector('[data-status="SUCCESS"]');
    if (hasSuccess) {
      downloadAllBtn.removeAttribute('disabled');
    } else {
      downloadAllBtn.setAttribute('disabled', 'true');
    }
  }

  function updateGlobalProgress() {
    return; // Neutralisé : barre globale + ETA pilotées par la brique commune wama-global-progress.js.
    if (!config.globalProgressUrl) return;

    fetch(config.globalProgressUrl)
      .then(response => response.json())
      .then(data => {
        const progressBar = document.getElementById('globalProgressBar');
        const statsText = document.getElementById('globalProgressStats');
        const pct = document.getElementById('globalProgressPct');
        const globalStatus = document.getElementById('globalStatus');
        const progress = data.overall_progress || 0;
        if (progressBar) progressBar.style.width = progress + '%';
        if (statsText) statsText.textContent = `${data.success}/${data.total} terminé · ${data.running} en cours`;
        if (window.WamaEta) WamaEta.render(document.getElementById('globalEta'), WamaEta.aggregateAll());
        if (pct) pct.textContent = progress ? progress + '%' : '';
        if (globalStatus) {
          const active = (data.total || 0) > 0;
          globalStatus.style.opacity = active ? '1' : '0';
          globalStatus.style.pointerEvents = active ? '' : 'none';
        }
      })
      .catch(error => console.error('Error updating global progress:', error));
  }

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

  // Curseur commun remis à l'équilibre : `input` réveille le listener délégué de wama-params.js
  // (valeur + tricolore), comme un geste de l'utilisateur.
  function resetIntent(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.value = '50';
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }

  // Reset button
  const resetBtn = document.getElementById('resetOptions');
  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      // Detect active tab
      const audioSettings = document.getElementById('audioSettings');
      const audioActive = audioSettings && audioSettings.style.display !== 'none';

      if (audioActive) {
        // Reset audio settings (défaut « auto » depuis le curseur C ; `change` réveille la
        // bascule du curseur et WamaModelCaps).
        const audioEngineEl = document.getElementById('audioEngine');
        if (audioEngineEl) {
          audioEngineEl.value = 'auto';
          audioEngineEl.dispatchEvent(new Event('change', { bubbles: true }));
        }

        const audioModeEl = document.getElementById('audioMode');
        if (audioModeEl) audioModeEl.value = 'both';

        const audioStrengthEl = document.getElementById('audioDenoisingStrength');
        if (audioStrengthEl) {
          audioStrengthEl.value = '0.5';
          const display = document.getElementById('audioStrengthValue');
          if (display) display.textContent = '0.5';
        }

        const audioQualityEl = document.getElementById('audioQuality');
        if (audioQualityEl) audioQualityEl.value = '64';
        resetIntent('audioQualityIntent');
      } else {
        // Reset image/video settings
        const defaultAiModelEl = document.getElementById('defaultAiModel');
        if (defaultAiModelEl && defaultAiModelEl.options.length > 0) {
          defaultAiModelEl.selectedIndex = 0;
          syncMediaAutoOptions();
        }
        const factorEl = document.getElementById('mediaUpscaleFactor');
        if (factorEl) factorEl.value = '4';
        resetIntent('mediaQualityIntent');

        const defaultDenoiseEl = document.getElementById('defaultDenoise');
        if (defaultDenoiseEl) defaultDenoiseEl.checked = false;

        const defaultBlendEl = document.getElementById('defaultBlendFactor');
        if (defaultBlendEl) {
          defaultBlendEl.value = '0';
          const display = document.getElementById('blendValue');
          if (display) display.textContent = '0';
        }
      }
    });
  }

  // Initialize
  initImport();
  initUrlUpload();
  initExistingRows();
  initBulkActions();
  bindRowActions(document);

  // Bind actions to existing modals (loaded from Django template)
  setTimeout(() => {
    bindRowActions(document);
  }, 100);

  // Update global progress every 2 seconds
  updateGlobalProgress();
  setInterval(updateGlobalProgress, 2000);

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
