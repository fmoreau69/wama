document.addEventListener('DOMContentLoaded', function () {
  const config = window.TRANSCRIBER_APP || {};
  const csrfToken = config.csrfToken;
  const queueContainer = document.getElementById('transcriptQueue');
  // Bouton de cycle : mécanisme plug-and-play commun — l'icône ▶/⏹/↻ suit data-status des cards
  // (cohérent avec les autres apps ; refreshCard re-rend la card entière depuis le serveur).
  if (window.WamaCycleButton && queueContainer) {
    WamaCycleButton.autoSync({ container: queueContainer, cardSelector: '.synthesis-card' });
  }
  const speakButton = document.getElementById('transcriber-speak-btn');
  const liveOutput = document.getElementById('live-transcription-output');
  const liveStatus = document.getElementById('live-transcription-status');

  // Polling + état vide délégués au module commun (common/js/wama-app-base.js).
  const _poller = new WamaApp.Poller({
    urlTemplate: config.progressUrlTemplate,
    onData: function (id, data) { updateCard(id, data); },
    interval: 1200,
    maxFails: 10,
  });

  // Helpers génériques délégués au module commun (common/js/wama-app-base.js).
  const getUrl     = WamaApp.getUrl;
  const escapeHtml = WamaApp.escapeHtml;
  function csrfHeaders(extra = {}) { return WamaApp.csrfHeaders(csrfToken, extra); }

  // ======================================================================
  // Upload
  // ======================================================================
  // Ajoute TOUS les paramètres du volet droit au FormData (pas seulement
  // backend/hotwords/preprocess) afin que l'élément DRAFT capture l'état complet
  // du volet au moment du dépôt.
  // Chaque réglage que le SCHÉMA met au volet (`_panelReadValues`) — plus de liste de champs.
  function _appendPanelParams(body) {
    const v = _panelReadValues();
    Object.keys(v).forEach(function (k) {
      body.append(k, typeof v[k] === 'boolean' ? (v[k] ? '1' : '0') : v[k]);
    });
  }

  // ── Toast : brique commune (wama-app-base.js), zéro dialogue bloquant ──
  function showToast(message, type) {
    if (window.WamaApp && WamaApp.toast) WamaApp.toast(message, type);
    else console.info('[Transcriber]', message);
  }

  function updateQueueCount() {
    const badge = document.getElementById('queueCount');
    if (!badge) return;
    const cards = document.querySelectorAll('#transcriptQueue .synthesis-card');
    badge.textContent = cards.length;
  }

  // ── Voie d'import : brique commune WamaImport (wama-import.js) — portage 2026-09-07 ──
  //
  // Le transcriber est la 1ʳᵉ app EN PLACE à l'adopter (plan « fichiers d'entrée »,
  // MEDIA_STORAGE_TIERING §8 ; jusqu'ici la brique n'était chargée que par les apps GÉNÉRÉES).
  // Ce qui vivait ici — boucle upload → consolidation → reload, câblage de la zone de dépôt,
  // du sélecteur de fichiers et du sélecteur de dossier — est exactement le contrat de la
  // brique ; l'app ne DÉCLARE plus que ses spécificités :
  //   • `extraFields`      : les paramètres du volet droit voyagent avec chaque dépôt (l'élément
  //                          DRAFT capture l'état complet du volet, comme avant) ;
  //   • `consolidateField` : 'ids' — la vue `consolidate` est la fabrique commune
  //                          (`queue_manipulation`), qui lit aussi bien le JSON que le champ répété.
  // Comportements PRÉSERVÉS par les défauts de la brique : lot détecté seulement sur un fichier
  // déposé SEUL (`batchScope:'single'`), `WamaFM.uploaded()` après chaque envoi, rechargement
  // de la page à la fin (les DRAFT sont rendus serveur — staging supprimé le 2026-06-29), et le
  // drop de dossier récursif (`WamaFolderImport`, porté par la brique depuis le 05/09).
  // La médiathèque n'a rien à câbler : son bouton injecte le File dans #transcriber-file et
  // déclenche `change`, que la brique écoute.
  function initImport() {
    if (typeof window.WamaImport !== 'function') {
      // Défaut le plus silencieux qui soit (une zone de dépôt que rien n'écoute) → on le DIT.
      showToast("Voie d'import non chargée (wama-import.js) — dépôt impossible", 'danger');
      console.error('[Transcriber] WamaImport absent : wama-import.js non chargé par le gabarit');
      return;
    }
    window._import = WamaImport({
      uploadUrl:        config.uploadUrl,
      consolidateUrl:   config.consolidateUrl,
      consolidateField: 'ids',
      csrfToken:        csrfToken,
      dropZoneId:       'dropZoneTranscriber',
      fileInputId:      'transcriber-file',
      folderInputId:    'transcriberFolderInput',
      batch:            window._batchImport,
      extraFields:      function (fd) { _appendPanelParams(fd); },
    });
  }

  // ── Actions de LOT (▶ ⧉ 🗑) : brique commune queue-actions.js (portage 2026-08-23).
  // Les URLs sont émises par le partial `common/_batch_card.html`, dérivées de la convention
  // de routes `batch/<pk>/<action>/` — l'app n'en construit plus aucune. Les trois handlers
  // qui vivaient ici faisaient le même confirm+POST+reload que dans 7 autres apps.


  // NB : sortir/entrer une card d'un batch = DRAG souris façon Solitaire (PAS un bouton — déjà trop
  // de boutons). Backend prêt : POST config.removeFromBatchUrlTemplate (sortie → batch-of-1 isolé) +
  // consolidate (entrée). Le handler de drag (SortableJS) sera ajouté en session VISUELLE (avec P2),
  // et posera sessionStorage['wama_focus_card'] sur l'id déplacé pour le repérer après reload.


  // initUpload / initDragDrop SUPPRIMÉS (2026-09-07) : sélecteur de fichiers, zone de dépôt
  // (clic, survol, drop récursif) et sélecteur de dossier sont câblés par WamaImport (initImport).

  function initYoutube() {
    // Import par URL : réutilise le FORMALISME BATCH commun (comme converter et
    // describer). L'URL (YouTube/Vimeo…, lien direct audio/vidéo, ou chemin de
    // fichier accessible au serveur) = un batch d'1 ligne → même parseur +
    // consolidation. Le téléchargement (audio pour les plateformes média) se fait
    // au démarrage de la tâche (common ensure_local_input). initUrlImport
    // (commun) gère input/bouton/Entrée/spinner ; ingestText (commun) pousse dans
    // le pipeline batch. Plus de champ 'youtube_url' ni d'endpoint dédié.
    WamaApp.initUrlImport({
      inputId: 'youtubeUrl',
      buttonId: 'youtubeSubmitBtn',
      onEmpty: function () { showToast('Veuillez entrer une URL', 'warning'); },
      onSubmit: function (url) {
        if (!window._batchImport) throw new Error("Import batch non initialisé");
        return window._batchImport.ingestText(url + '\n', 'url.txt');
      },
    });
  }

  // ======================================================================
  // Card rendering
  // ======================================================================
  // appendCard SUPPRIMEE (code mort — aucun appelant ; ~85 lignes de markup
  // qui divergeaient deja du serveur). Source unique = _transcript_card.html (A2-9).

  function updateCard(id, data) {
    const card = queueContainer ? queueContainer.querySelector(`.synthesis-card[data-id="${id}"]`) : null;
    if (!card) { stopPolling(id); return; }

    let progress = Math.min(100, Math.max(0, data.progress || 0));
    const status = (data.status || 'PENDING').toUpperCase();
    // Succès = barre PLEINE : ignore un cache de progression périmé (ex. 20 % laissé par un stop/relance
    // rapide) qui donnait une card SUCCESS avec une barre incohérente.
    if (status === 'SUCCESS') progress = 100;

    // Update progress bar
    const bar = card.querySelector('.wama-progress-fill');
    const progressText = card.querySelector('.progress-text');
    if (bar) {
      bar.style.width = `${progress}%`;
      if (status === 'RUNNING') bar.classList.add('active');
      else bar.classList.remove('active');
    }
    if (progressText) progressText.textContent = `${progress}%`;

    // seedSeconds = estimation a priori/apprise (eta_estimator) → ETA affichée dès le départ,
    // avant que le débit observé ne prenne le relais (WamaEta fusionne seed + observé).
    if (window.WamaEta) WamaEta.render(card.querySelector('.wama-eta'),
      WamaEta.update(id, { progress: progress, status: status,
                           seedSeconds: data.estimated_seconds, modelLoaded: false }));

    // Update status badge
    const badge = card.querySelector('.status-badge');
    if (badge) {
      badge.textContent = status;
      badge.className = 'badge status-badge ' + ({
        PENDING: 'bg-secondary', RUNNING: 'bg-warning',
        SUCCESS: 'bg-success', FAILURE: 'bg-danger'
      }[status] || 'bg-secondary');
    }

    // Classe d'ÉTAT de la card — par `classList`, JAMAIS par `className =`.
    //
    // ⚠ CORRIGÉ le 2026-08-23. Cette ligne réassignait la classe ENTIÈRE et effaçait donc
    // `wama-card` au premier changement de statut. Conséquences mesurées au navigateur :
    //   • le scénario `transcriber.duplicate_delete` échouait depuis le 22/08 (« la file ne
    //     bouge pas ») — il compte les cards par `.wama-card[data-id]` et n'en voyait qu'UNE
    //     sur trois, puis cliquait le bouton d'une card qu'il n'avait pas comptée ;
    //   • la brique commune de suppression (`queue-actions.js`) retire la card par
    //     `.wama-card[data-id]` : une card ayant perdu la classe ne disparaissait plus de
    //     l'écran après suppression.
    // Le diagnostic consigné le 22/08 disait « suspecter mon test avant l'app » : le test avait
    // bien deux défauts (handle détaché, lot replié), mais celui-ci était dans l'app.
    card.classList.add('synthesis-card', 'wama-card');   // filet : cards bâties avant ce correctif
    // `data-status` pilote la COULEUR d'état (CSS sur l'attribut) et le bouton de cycle : les
    // classes processing/success/error posées ici recopiaient l'information — retirées le
    // 2026-09-18. ⚠ Le filet ci-dessus reste : il concerne `wama-card`, pas l'état.
    card.dataset.status = status;
    card.dataset.elementStatus = status;   // l'état de l'ÉLÉMENT (le suivi s'y fie, cf. initExistingCards)

    // Propriétés fichier (codec • kHz • canaux) : la ligne n'est remplie qu'à la création de card et
    // n'était jamais rafraîchie → certaines cards la perdaient (calcul différé après upload, ou rebuild).
    // Ici on la (ré)affiche dès que le poll les renvoie → cohérent + persistant.
    if (data.properties) {
      const propText = card.querySelector('.card-properties-text');
      const propEl = card.querySelector('.card-properties');
      if (propText) propText.textContent = data.properties;
      if (propEl) propEl.style.display = '';
    }

    // État textuel de la card : pendant RUNNING, affiche l'action en cours (dernier message
    // de log) si dispo, sinon « Traitement… ». Évite aussi « En attente » figé.
    const st = card.querySelector('.card-state');
    if (st) {
      if (status === 'RUNNING') {
        const msg = (data.status_message || '').trim();
        st.className = 'card-state text-warning';
        st.innerHTML = '<i class="fas fa-spinner fa-spin"></i> ' + (msg ? escapeHtml(msg) : 'Traitement…');
      }
      else if (status === 'PENDING') { st.className = 'card-state text-body-secondary'; st.textContent = 'En attente'; }
      else if (status === 'FAILURE') { st.className = 'card-state text-danger'; st.innerHTML = '<i class="fas fa-triangle-exclamation"></i> Échec'; }
      else { st.className = 'card-state'; st.textContent = ''; }
    }

    // Les PROCESS de la card (bande commune) suivent le traitement en place.
    if (window.WamaApp && WamaApp.updateProcessRows) WamaApp.updateProcessRows(card, data.processes);

    // Update live transcription display
    updateLiveTranscriptionFromQueue(id, status, data.partial_text);

    // Fin de process : agir UNIQUEMENT sur un statut terminal réel (pas sur
    // progress>=100 seul, qui peut précéder le passage en SUCCESS).
    if (status === 'SUCCESS') {
      stopPolling(id);
      // Reload → rendu serveur complet : preview compacte, options à jour,
      // onglet cohérence, barre à 100 %. Évite le « revert » des options.
      setTimeout(() => location.reload(), 300);
    } else if (status === 'FAILURE') {
      stopPolling(id);
      refreshCard(id);
    }

  }

  // Card RENDUE SERVEUR — source unique : partial _transcript_card.html via
  // transcriber:card_html. Remplace rebuildActions (3e copie du markup d'actions +
  // save/restore manuel de 9 data-attributes) — audit A2-10.
  // Redemandée par la brique commune (WamaApp.fetchCard, portage 2026-09-22 — la copie locale
  // du fetch + parse vivait ici).
  function refreshCard(id) {
    WamaApp.fetchCard(window.TRANSCRIBER_APP.cardHtmlUrlTemplate, id).then(fresh => {
      if (!fresh) return;
      const card = document.querySelector(`.synthesis-card[data-id="${id}"]`);
      if (card) card.replaceWith(fresh);
      else document.getElementById('transcriptQueue')?.prepend(fresh);
    });
  }

  // ======================================================================
  // Card actions
  // ======================================================================
  // Bouton de cycle commun, délégué UNE fois sur la FILE, comme les autres apps (describer,
  // imager…). ⚠⚠ Il était lié sur chaque CARD jusqu'au 2026-10-13 : la card remplacée par une
  // neuve (case d'un process cochée, `refreshCard`) n'avait plus d'écouteur, et tous ses ▶ — celui
  // de la card comme ceux des process — restaient muets jusqu'au rechargement (constat de Fabien :
  // « Locuteurs » coché, la flèche ne lançait rien). Le repli `.start-btn` est parti avec : aucun
  // gabarit n'en produit plus, et la brique est montée par `base.html`.
  // `btn.dataset.process` : le ▶ d'UN process de la bande → lancement borné (route
  // `start/<id>/<process>/`) ; sans lui, le ▶ de la card lance tout ce qui est dû.
  if (queueContainer) {
    WamaCycleButton.wire(queueContainer, {
      start: (id, btn, process) => handleStart(id, process),
      stop: (id) => handleStop(id),
    });
  }

  // ⚙, 🗑 et ⧉ : rien à lier par card — la brique commune queue-actions.js délègue sur le
  // document (portage 2026-08-23), valable aussi pour les cards rendues plus tard.

  // ⏹ Stop : arrête le traitement en cours (endpoint commun) → item relançable (↻). La card est
  // rafraîchie par le flux normal (updateCard → refreshCard) qui repassera le bouton en ↻.
  function handleStop(id) {
    const url = getUrl(config.stopUrlTemplate, id);
    fetch(url, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({}),
    })
      .then(r => r.json())
      .then(data => {
        if (data && data.id) updateCard(id, data);   // statut → FAILURE : badge/barre/actions (↻)
      })
      .catch(() => {});
  }

  function handleStart(id, process) {
    const card = queueContainer.querySelector(`.synthesis-card[data-id="${id}"]`);
    // Relance PENDANT le traitement (modale « Enregistrer & démarrer ») : on stoppe d'abord pour
    // éviter le 409 « déjà en cours », puis on relance avec les params à jour.
    if (card && (card.dataset.status || '').toUpperCase() === 'RUNNING') {
      card.dataset.status = 'PENDING';   // évite la récursion + reflète l'arrêt imminent
      fetch(getUrl(config.stopUrlTemplate, id), {
        method: 'POST', headers: csrfHeaders({ 'Content-Type': 'application/json' }), body: '{}',
      }).then(() => doStart(id, card, process)).catch(() => doStart(id, card, process));
      return;
    }
    doStart(id, card, process);
  }

  function doStart(id, card, process) {
    const url = WamaCycleButton.processUrl(getUrl(config.startUrlTemplate, id), process);
    if (!card) card = queueContainer.querySelector(`.synthesis-card[data-id="${id}"]`);

    fetch(url, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({}),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          showToast(data.error, 'danger');
          return;
        }
        // Update card to RUNNING state
        if (card) {
          card.dataset.status = 'RUNNING';
          // `classList` et non `className =` : voir le correctif du 2026-08-23 plus haut —
          // réassigner la classe entière effaçait `wama-card`, que la brique de suppression
          // et les scénarios utilisent pour identifier une card.
          card.classList.add('synthesis-card', 'wama-card');
          const badge = card.querySelector('.status-badge');
          if (badge) {
            // Libellé et classe VIENNENT des maps communes : « RUNNING » et `bg-warning` écrits
            // en dur affichaient la valeur BRUTE à l'utilisateur et redéclaraient une 3ᵉ fois la
            // table de présentation des états (2026-09-18).
            const A = window.WamaApp || {};
            badge.textContent = (A.STATUS_LABEL && A.STATUS_LABEL.RUNNING) || 'En cours';
            badge.className = 'badge status-badge ' + ((A.STATUS_BADGE && A.STATUS_BADGE.RUNNING)
                                                       || 'bg-warning text-dark');
          }
          const bar = card.querySelector('.wama-progress-fill');
          if (bar) { bar.style.width = '0%'; bar.classList.add('active'); }
          const pt = card.querySelector('.progress-text');
          if (pt) pt.textContent = '0%';

          // Boutons VISIBLES + actifs pendant le traitement : on reconstruit les actions en RUNNING
          // → le bouton de cycle passe en ⏹ Stop et ⚙ Paramètres reste (inspecter/modifier en cours).
          refreshCard(id);
        }
        startPolling(id);
      })
      .catch(err => showToast(err.message || 'Erreur', 'danger'));
  }

  // 🗑 RÉSIDU de suppression — la brique commune (queue-actions.js) porte la confirmation, le
  // POST, le retrait de la card, le lot vidé, l'ETA et le signal au gestionnaire de fichiers.
  // Ne reste ici que ce qui dépend d'un état LOCAL à l'app : la sélection de l'inspecteur, le
  // poller (pas encore `WamaApp.Poller` ici) et deux libellés d'en-tête.
  // Portage 2026-08-23 — le binder `.delete-btn` de `bindCardActions` a été retiré au même geste.
  WamaQueueActions.onDeleted(function (id) {
    if (_inspector && String(id) === String(_inspector.state().itemId)) _inspector.deselect();  // évite des actions inspecteur orphelines
    stopPolling(id);
  });


  // ======================================================================
  // Settings modal
  // ======================================================================
  // ⚙ de LOT — ouvreur DÉCLARÉ à la brique commune (queue-actions.js), portage 2026-08-23.
  WamaQueueActions.onBatchSettings(function (id, btn) { openBatchSettingsModal(btn); });

  function openBatchSettingsModal(btn) {
    // Modale de BATCH dédiée (champs générés du schéma, context 'batch') — le
    // détournement de la modale item (titre échangé + _settingsBatchId) est mort.
    const modal = document.getElementById('batchSettingsModal');
    if (!modal) return;
    modal.dataset.batchId = btn.dataset.batchId;
    const idBadge = document.getElementById('batchSettingsBatchId');
    if (idBadge) idBadge.textContent = '#' + btn.dataset.batchId;
    // The batch modal's model select is filled by WamaParams from the catalogue (its own source
    // binding) — no more copying the panel's options.
    new bootstrap.Modal(modal).show();
  }

  function saveBatchSettings(andStart) {
    const modal = document.getElementById('batchSettingsModal');
    const bid = modal && modal.dataset.batchId;
    if (!bid || !window.WamaParams) return;
    const payload = WamaParams.read(document.getElementById('transcriberBatchParams'));
    payload.temperature = 0;      // réglages retirés de l'UI (ASR = reproductibilité)
    payload.max_tokens = 32768;
    fetch(getUrl(config.batchUpdateUrlTemplate, bid), {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    })
      .then(r => r.json())
      .then(() => {
        const m = bootstrap.Modal.getInstance(modal);
        if (m) m.hide();
        if (andStart) {
          fetch(getUrl(config.batchStartUrlTemplate, bid), { method: 'POST', headers: csrfHeaders() })
            .finally(() => location.reload());
        } else {
          location.reload();
        }
      })
      .catch(() => showToast('Erreur lors de la mise à jour du batch', 'danger'));
  }
  document.addEventListener('click', function (e) {
    if (e.target.closest('#saveBatchSettingsBtn')) saveBatchSettings(false);
    if (e.target.closest('#saveBatchSettingsAndStartBtn')) saveBatchSettings(true);
  });

  // ⚙ item — ouvreur DÉCLARÉ à la brique commune (queue-actions.js) : une délégation unique,
  // valable pour les cards rendues après coup (portage 2026-08-23).
  WamaQueueActions.onSettings(function (id, btn) { openSettingsModal(btn); });

  // ⚙ item — le CYCLE commun `WamaParams.settingsModal` (portage 2026-09-25 ; la modale statique
  // `#settingsModal`, `saveSettings` et la mise à jour de la card champ par champ vivaient ici).
  // La modale est GÉNÉRÉE du schéma à chaque ouverture ; ce qui reste propre au transcriber est
  // DÉCLARÉ en crochets :
  //   - les valeurs viennent des data-* du ⚙ (la card les porte toutes) — le select du modèle se
  //     remplit du catalogue par la brique et resélectionne la valeur de la card (F4b ⑦ : le
  //     crochet `decorate` qui recopiait les moteurs du volet est retiré) ;
  //   - `onSaved` re-rend la card depuis le serveur (plus de réécriture à la main de ses champs),
  //     puis relance si « Enregistrer et démarrer ».
  function openSettingsModal(btn) {
    if (!window.WamaParams || !window.WAMA_TRANSCRIBER_SCHEMA) {
      showToast('Formulaire indisponible (WamaParams non chargé) — recharger la page.', 'danger');
      return;
    }
    const id = btn.dataset.id;
    const values = {
      backend: btn.dataset.backend || 'auto',
      hotwords: btn.dataset.hotwords || '',
      preprocess_audio: btn.dataset.preprocessAudio === 'true',
      level_speech: btn.dataset.levelSpeech === 'true',
      vad_mode: btn.dataset.vadMode || 'auto',
      language_mode: btn.dataset.languageMode || 'auto',
      enable_diarization: btn.dataset.enableDiarization !== 'false',
      diarization_model: btn.dataset.diarizationModel || 'speaker-diarization-3.1',
      generate_summary: btn.dataset.generateSummary === 'true',
      summary_type: btn.dataset.summaryType || 'structured',
      verify_coherence: btn.dataset.verifyCoherence === 'true',
    };
    return WamaParams.settingsModal({
      id: id,
      title: 'Paramètres de transcription',
      titleIcon: 'fa-cog',
      schema: window.WAMA_TRANSCRIBER_SCHEMA,
      values: values,
      formClass: 'transcriber-settings-form',
      footerTplId: 'transcriberSettingsFooterTpl',
      saveUrl: getUrl(config.settingsUrlTemplate, id),
      csrf: csrfToken,
      onSaved: function (savedId, restart) {
        refreshCard(savedId);
        if (restart) handleStart(savedId);
      },
    });
  }

  // Toggle summary type group visibility — global panel (the item modal's is handled by the
  // schema's `show_if`, inside the shared renderer)
  document.addEventListener('change', function(e) {
    if (e.target && e.target.id === 'globalGenerateSummary') {
      const group = document.getElementById('globalSummaryTypeGroup');
      if (group) group.style.display = e.target.checked ? 'block' : 'none';
    }
  });

  // ======================================================================
  // Polling
  // ======================================================================
  // Polling de progression — délégué à WamaApp.Poller (comportement identique :
  // résilient aux erreurs réseau transitoires, updateCard protégé par try/catch).
  function startPolling(id) { _poller.start(id); }
  function stopPolling(id) { _poller.stop(id); }

  // (État vide : rendu par la file commune et basculé par sa brique, 2026-10-20.)

  // ======================================================================
  // Bulk actions
  // ======================================================================
  function initBulkActions() {
    // ▶ Start all and 🗑 Clear all: shared `queue-actions.js` brick (2026-10-17, URLs passed to
    // the partial). The ▶ declares its follow-up: say so when nothing was left to start,
    // otherwise reload to get fresh card states.
    WamaQueueActions.onQueueStarted(data => {
      if (!(data.started_ids || []).length) { showToast('Aucune transcription à démarrer.', 'info'); return; }
      window.location.reload();
    });
    // ⚠ Bulk download: NO wiring here (2026-08-30). The dropdown used to be rebuilt in JS —
    // four formats HARD-CODED, URL forged by `startAllUrl.replace('start_all','download_all')`.
    // The queue toolbar now renders it from the catalogue (`export_formats`) via
    // `common/_download_button.html` with `split=False`; its `disabled` state is toggled by the
    // shared global progress bar since 2026-10-17 (`updateDownloadAllState` removed: it counted
    // DOM cards, which a status filter can hide — the bar reads the server count).
    // Enregistrement automatique : `autoSave` de l'inspecteur commun (2026-09-27), sur les seuls
    // gestes réels — l'écouteur local d'avant partait aussi sur les `change` que l'inspecteur
    // émet en affichant une card, et réécrivait l'élément à chaque clic.

    // Item settings modal: buttons are delegated by the shared cycle (`WamaParams.settingsModal`).

    // Reset button
    const resetBtn = document.getElementById('resetOptions');
    if (resetBtn) {
      // « ↺ Par défaut » : les défauts du SCHÉMA (brique commune applyDefaults), posés par
      // l'applicateur de l'inspecteur (il connaît les noms legacy des radios) ; puis on garde.
      resetBtn.addEventListener('click', () => {
        const host = document.getElementById('panelSettings');
        const vals = WamaParams.applyDefaults(host, window.WAMA_TRANSCRIBER_SCHEMA || [], 'panel');
        if (_inspector && _inspector.apply) _inspector.apply(vals);
        savePanelSettings();
      });
    }
  }



  // ======================================================================
  // Inspecteur (niveau 2) — le volet droit reflète la card sélectionnée
  // ======================================================================
  let _inspector = null;   // instance WamaInspector (module commun) — créée dans initInspector

  // Les valeurs du volet, lues PAR LE SCHÉMA (lecteur dérivé de l'inspecteur commun,
  // `WamaInspector.initFromSchema`) : tout param de contexte `panel`, noms legacy compris.
  function _panelReadValues() {
    return (_inspector && _inspector.read) ? _inspector.read() : {};
  }

    // Actions de la card inspectée (callback WamaInspector) : clone des boutons de la card + rebind.
  function _renderItemActions(host, card) {
    WamaInspector.cloneActions(host, card.querySelector('.btn-group-actions'),
      '<i class="fas fa-crosshairs text-info"></i> Actions — élément #' + card.dataset.id);
  }

  // Sauvegarde des réglages de l'élément inspecté (callback WamaInspector).
  function saveInspectorItem(id) {
    if (!id || !config.settingsUrlTemplate) return;
    const card = queueContainer ? queueContainer.querySelector(`.synthesis-card[data-id="${id}"]`) : null;
    // Le volet inclut désormais Température + Max tokens → on lit tout depuis le panneau.
    const payload = _panelReadValues();
    fetch(getUrl(config.settingsUrlTemplate, id), {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    })
      .then(r => r.json())
      // La card est re-rendue par le serveur : ses data-* (le ⚙) viennent de `gear_data`,
      // dérivé du schéma — plus de recopie champ par champ ici.
      .then(() => { if (card) refreshCard(id); })
      .catch(() => showToast('Erreur lors de l\'enregistrement', 'danger'));
  }

  // Sauvegarde des réglages du batch inspecté → tous les items (callback WamaInspector).
  function saveInspectorBatch(bid) {
    if (!bid || !config.batchUpdateUrlTemplate) return;
    fetch(getUrl(config.batchUpdateUrlTemplate, bid), {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(_panelReadValues()),
    }).then(r => r.json()).catch(() => showToast('Erreur lors de l\'enregistrement du batch', 'danger'));
  }

  // Routage de la sauvegarde via l'inspecteur commun (item / batch / défauts de l'utilisateur,
  // ces derniers par `saveGlobalUrl` — brique commune, 2026-09-27).
  function savePanelSettings() { if (_inspector) _inspector.save(); }

  // Crée l'inspecteur commun (WamaInspector) câblé aux spécificités du transcriber.
  function initInspector() {
    if (!queueContainer || !window.WamaInspector || !WamaInspector.initFromSchema) return;
    // initFromSchema : panel.read/apply et cardSettings DÉRIVÉS du schéma (params.py,
    // dom_id/radio_name legacy scopés par contexte) — plus de lecteurs/applicateurs à la main.
    _inspector = WamaInspector.initFromSchema({
      queueContainer: queueContainer,
      panelContainer: document.getElementById('panelSettings'),
      schema: window.WAMA_TRANSCRIBER_SCHEMA || [],
      cardSelector: '.synthesis-card',
      hideOnInspect: ['resetOptions'],
      settingsTitleSelector: '#settings-section .right-panel-section-title',
      settingsTitleInspect: '<i class="fas fa-cog me-1"></i> Paramètres de l\'élément',
      renderItemActions: _renderItemActions,
      // Actions d'un LOT : brique commune (résout la card mère depuis son IDENTIFIANT).
      renderBatchActions: function (host, batchId) { WamaInspector.cloneBatchActions(host, batchId); },
      saveItem: saveInspectorItem,
      saveBatch: saveInspectorBatch,
      saveGlobalUrl: config.saveUserSettingsUrl,
      autoSave: true,
      itemLabel: (id) => "l'élément #" + id,
    });
  }

  // ======================================================================
  // Live transcription
  // ======================================================================
  function updateLiveTranscriptionFromQueue(transcriptId, status, partialText) {
    if (!liveOutput || !liveStatus) return;
    if (speakButton && speakButton.classList.contains('active')) return;

    const firstRunning = queueContainer ? queueContainer.querySelector('.synthesis-card[data-status="RUNNING"]') : null;

    if (!firstRunning) {
      if (liveOutput.textContent !== 'Appuyez sur Speak puis commencez à parler pour voir le texte apparaître ici en temps réel.') {
        liveOutput.textContent = 'Aucune transcription en cours.';
        liveStatus.textContent = 'En attente...';
      }
      return;
    }

    if (firstRunning.dataset.id !== String(transcriptId)) return;

    if (status === 'RUNNING') {
      liveStatus.textContent = `Transcription #${transcriptId} en cours...`;
    } else if (status === 'SUCCESS') {
      liveStatus.textContent = `Transcription #${transcriptId} terminée`;
    } else if (status === 'FAILURE') {
      liveStatus.textContent = `Transcription #${transcriptId} échouée`;
    }

    if (partialText && partialText.trim()) {
      displayTextWithHighlight(partialText);
    }
  }

  function displayTextWithHighlight(text) {
    if (!liveOutput) return;
    const words = text.split(/(\s+)/);
    let lastWordIndex = -1;
    for (let i = words.length - 1; i >= 0; i--) {
      if (words[i].trim().length > 0) { lastWordIndex = i; break; }
    }
    if (lastWordIndex >= 0) {
      const htmlParts = words.map((word, index) => {
        if (index === lastWordIndex) {
          return `<mark style="background-color: #ffc107; color: #000; padding: 2px 4px; border-radius: 3px;">${escapeHtml(word)}</mark>`;
        }
        return escapeHtml(word);
      });
      liveOutput.innerHTML = htmlParts.join('');
    } else {
      liveOutput.textContent = text;
    }
  }

  // ======================================================================
  // Speak — le port « en direct » écoute par la brique COMMUNE de l'assistant
  // (`WamaAssistantListen.capture`, 2026-10-12). Jusque-là : la reconnaissance du navigateur,
  // qui envoie l'audio à Google, en français imposé. Désormais le même micro, le même découpage
  // et la même route (`/api/stt/`) que la conversation avec l'assistant : moteur choisi au
  // PROFIL (Albert ou Whisper local), phrases fantômes retirées côté serveur.
  // ======================================================================
  function initSpeech() {
    if (!speakButton || !liveOutput || !liveStatus) return;
    const listen = window.WamaAssistantListen;
    if (!listen || !listen.capture) {
      speakButton.disabled = true;
      liveStatus.textContent = 'Écoute indisponible sur cette page';
      return;
    }

    const PHASES = { listening: 'Écoute en cours…', hearing: 'Je vous écoute…', transcribing: 'Transcription…' };
    let session = null;           // la capture en cours
    let starting = false;
    let text = '';

    function setIdle(msg) {
      session = null;
      speakButton.classList.remove('active');
      speakButton.innerHTML = '<i class="fas fa-microphone"></i> Speak';
      if (msg) liveStatus.textContent = msg;
    }

    function showText() {
      if (text) displayTextWithHighlight(text);
      else liveOutput.textContent = '...';
    }

    async function startAll() {
      text = '';
      starting = true;
      // Révèle la zone de transcription live (masquée par défaut depuis sa fusion dans la card d'entrée)
      var liveBox = document.getElementById('transcriberLive');
      if (liveBox) { liveBox.style.display = ''; liveBox.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
      speakButton.classList.add('active');
      speakButton.innerHTML = '<i class="fas fa-stop"></i> Stop';
      liveStatus.textContent = 'Ouverture du micro…';
      try {
        session = await listen.capture({
          record: true,                               // l'audio complet devient la card
          onPhase: (phase) => { if (PHASES[phase]) liveStatus.textContent = PHASES[phase]; },
          onText: (phrase) => { text = text ? text + '\n' + phrase : phrase; showText(); },
          onError: (message) => { liveStatus.textContent = message; },
          onEnd: uploadRealtime,
        });
        showText();
      } catch (err) {
        setIdle(err.message);
      }
      starting = false;
    }

    function stopAll() {
      if (!session) return;
      liveStatus.textContent = 'Fin de la transcription…';
      session.stop();                             // → onEnd → uploadRealtime (sauve la card)
    }

    // À l'arrêt : l'audio + le texte entendu → une card « temps réel » dans la file.
    function uploadRealtime(result) {
      const blob = result && result.recording;
      if (!blob || !blob.size || !config.saveRealtimeUrl) {
        setIdle(result && result.text ? 'Session terminée' : 'En attente...');
        return;
      }
      setIdle('Enregistrement dans la file…');
      const fd = new FormData();
      const ext = (blob.type.indexOf('ogg') >= 0) ? 'ogg' : 'webm';
      fd.append('audio', blob, 'realtime.' + ext);
      fd.append('text', result.text || '');
      fd.append('language', (result.language || 'fr').slice(0, 2));
      fd.append('engine', result.engine || '');
      fetch(config.saveRealtimeUrl, { method: 'POST', headers: { 'X-CSRFToken': csrfToken }, body: fd })
        .then(r => r.json())
        .then(d => {
          if (d && d.ok) { liveStatus.textContent = 'Ajouté à la file ✓'; setTimeout(() => location.reload(), 400); }
          else { liveStatus.textContent = 'Échec de l\'enregistrement dans la file'; }
        })
        .catch(() => { liveStatus.textContent = 'Erreur réseau'; });
    }

    speakButton.addEventListener('click', () => {
      if (starting) return;
      if (session) stopAll(); else startAll();
    });
  }

  // ======================================================================
  // Global progress
  // ======================================================================
  // (updateGlobalProgress retiré : la barre globale + l'ETA agrégée sont fournies par la
  //  brique commune wama-global-progress.js. Voir _global_progress.html dans le template.)

  // ======================================================================
  // Init
  // ======================================================================
  function initExistingCards() {
    if (!queueContainer) return;
    queueContainer.querySelectorAll('.synthesis-card[data-id]').forEach(card => {
      // L'état de l'ÉLÉMENT décide du suivi, pas l'état MONTRÉ (déduit des process) : une card
      // terminée dont un process optionnel reste à compléter se montre « en attente » — la
      // suivre la ferait recharger la page en boucle (le serveur répond « terminé »).
      const status = (card.dataset.elementStatus || card.dataset.status || '').toUpperCase();
      if (['PENDING', 'RUNNING', 'STARTED'].includes(status)) {
        startPolling(card.dataset.id);
      }
    });
  }

  // The model select is filled from the CATALOGUE by the common brick (WamaParams, `catalog`
  // source — route F4b ⑦, 2026-09-30) in every context: panel, item modal, batch modal. The app's
  // own filling (`loadBackendsAsync` + its `/transcriber/backends/` endpoint) is gone.

  initImport();
  initYoutube();
  initExistingCards();
  initSpeech();
  initBulkActions();
  initInspector();

  // Progression globale + ETA agrégée : désormais pilotées par la brique commune
  // wama-global-progress.js (auto-démarrée). On ne double pas le poller ici.
});
