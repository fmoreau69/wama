document.addEventListener('DOMContentLoaded', function () {
  const config = window.TRANSCRIBER_APP || {};
  const csrfToken = config.csrfToken;
  const fileInput = document.getElementById('transcriber-file');
  const queueContainer = document.getElementById('transcriptQueue');
  // Bouton de cycle : mécanisme plug-and-play commun — l'icône ▶/⏹/↻ suit data-status des cards
  // (cohérent avec les autres apps ; refreshCard re-rend la card entière depuis le serveur).
  if (window.WamaCycleButton && queueContainer) {
    WamaCycleButton.autoSync({ container: queueContainer, cardSelector: '.synthesis-card' });
  }
  const speakButton = document.getElementById('transcriber-speak-btn');
  const liveOutput = document.getElementById('live-transcription-output');
  const liveStatus = document.getElementById('live-transcription-status');
  const startProcessBtn = document.getElementById('transcriber-process-btn');
  const clearAllBtn = document.getElementById('transcriber-clear-btn');
  const downloadAllBtn = document.getElementById('transcriber-download-all-btn');
  const preprocessToggle = document.getElementById('preprocessingToggle');
  const toggleDatasetUrl = preprocessToggle ? preprocessToggle.dataset.preprocessUrl : '';

  // Polling + état vide délégués au module commun (common/js/wama-app-base.js).
  const _poller = new WamaApp.Poller({
    urlTemplate: config.progressUrlTemplate,
    onData: function (id, data) { updateCard(id, data); },
    interval: 1200,
    maxFails: 10,
  });
  const _empty = WamaApp.emptyState({
    container: queueContainer,
    cardSelector: '.synthesis-card',
    html: '<i class="fas fa-inbox fa-3x mb-3 text-white-50"></i><p class="text-white-50">Aucune transcription en attente</p>',
  });
  let preprocessEnabled = !!config.preprocessingEnabled;
  if (typeof config.preprocessingEnabled === 'string') {
    preprocessEnabled = config.preprocessingEnabled === 'true';
  }

  // Helpers génériques délégués au module commun (common/js/wama-app-base.js).
  const getUrl     = WamaApp.getUrl;
  const escapeHtml = WamaApp.escapeHtml;
  const wordCount  = WamaApp.wordCount;
  function csrfHeaders(extra = {}) { return WamaApp.csrfHeaders(csrfToken, extra); }

  function setWordCount(spanId, text) {
    const span = document.getElementById(spanId);
    if (!span) return;
    const n = wordCount(text);
    if (n > 0) { span.textContent = `${n} mot${n !== 1 ? 's' : ''}`; span.style.display = ''; }
    else { span.textContent = ''; span.style.display = 'none'; }
  }

  // ======================================================================
  // Upload
  // ======================================================================
  // Ajoute TOUS les paramètres du volet droit au FormData (pas seulement
  // backend/hotwords/preprocess) afin que l'élément DRAFT capture l'état complet
  // du volet au moment du dépôt.
  function _appendPanelParams(body) {
    const v = _panelReadValues();
    body.append('preprocess_audio', v.preprocess_audio ? '1' : '0');
    body.append('backend', v.backend);
    body.append('hotwords', v.hotwords);
    body.append('enable_diarization', v.enable_diarization ? '1' : '0');
    body.append('generate_summary', v.generate_summary ? '1' : '0');
    body.append('summary_type', v.summary_type);
    body.append('verify_coherence', v.verify_coherence ? '1' : '0');
  }

  // Mêmes paramètres sous forme d'objet (pour les POST de staging).
  function _panelParamsObj() {
    const v = _panelReadValues();
    return {
      preprocess_audio:   v.preprocess_audio ? '1' : '0',
      backend:            v.backend,
      hotwords:           v.hotwords,
      enable_diarization: v.enable_diarization ? '1' : '0',
      generate_summary:   v.generate_summary ? '1' : '0',
      summary_type:       v.summary_type,
      verify_coherence:   v.verify_coherence ? '1' : '0',
    };
  }

  async function uploadFile(file) {
    const body = new FormData();
    body.append('file', file);
    _appendPanelParams(body);

    try {
      const response = await fetch(config.uploadUrl, {
        method: 'POST', headers: csrfHeaders(), body,
      });
      const data = await response.json();
      if (data.error) throw new Error(data.error);
      // L'élément arrive en zone de staging (DRAFT) — il n'est PAS ajouté à la
      // file ici ; le rechargement affiche la zone « À valider » (rendu serveur).
      if (window.WamaFM) WamaFM.uploaded();  // fichier de travail ajouté → refresh filemanager
      return data.id;
    } catch (error) {
      showToast(`Erreur pour ${file.name}: ${error.message}`, 'danger');
      return null;
    }
  }

  // ── Toast : brique commune (wama-app-base.js) — plus d'alert() bloquant ──
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

  // ── Batch file detection — delegated to WamaBatchImport (common/js/batch-import.js)

  async function handleFiles(files) {
    const fileList = Array.from(files);
    if (fileList.length === 1 && window._batchImport) {
      if (await window._batchImport.detectAndHandle(fileList[0])) return;
    }
    // Upload tous les fichiers puis consolide en UN batch si plusieurs (le
    // serveur défait les batch-of-1 créés à l'upload). Couvre drag&drop,
    // explorateur Windows et sélecteur de fichiers.
    let any = false;
    for (const file of fileList) {
      const id = await uploadFile(file);
      if (id) any = true;
    }
    // Les fichiers importés deviennent des cards BROUILLON (DRAFT) dans la file : on recharge
    // pour le rendu serveur (enveloppe en batch via _auto_wrap_orphans). Staging supprimé (2026-06-29).
    if (any) location.reload();
  }

  // Staging (« à valider ») SUPPRIMÉ 2026-06-29 : les DRAFT sont des cards BROUILLON directement
  // dans la file (config via inspecteur, lancement via Lancer). Plus de zone ni de handlers staging.

  // ── Batch delete ─────────────────────────────────────────────────────────
  document.addEventListener('click', function(e) {
    const btn = e.target.closest('.batch-delete-btn');
    if (!btn) return;
    const batchId = btn.dataset.batchId;
    if (!confirm('Supprimer ce batch et toutes ses transcriptions ?')) return;
    const url = config.batchDeleteUrlTemplate.replace('/0/', `/${batchId}/`);
    fetch(url, {method: 'POST', headers: csrfHeaders()})
      .then(r => r.json())
      .then(() => {
        const el = btn.closest('.batch-group');
        if (el) el.remove();
        else location.reload();
        updateQueueCount();
        if (window.WamaFM) WamaFM.deleted();  // fichiers supprimés → refresh filemanager
      })
      .catch(() => showToast('Erreur lors de la suppression', 'danger'));
  });

  // ── Batch start/restart (lancer tous les éléments du batch) ───────────────
  document.addEventListener('click', function(e) {
    const btn = e.target.closest('.batch-start-btn');
    if (!btn) return;
    const batchId = btn.dataset.batchId;
    const url = config.batchStartUrlTemplate.replace('/0/', `/${batchId}/`);
    fetch(url, {method: 'POST', headers: csrfHeaders()})
      .then(r => r.json())
      .then(() => location.reload())
      .catch(() => showToast('Erreur lors du lancement du batch', 'danger'));
  });

  // NB : sortir/entrer une card d'un batch = DRAG souris façon Solitaire (PAS un bouton — déjà trop
  // de boutons). Backend prêt : POST config.removeFromBatchUrlTemplate (sortie → batch-of-1 isolé) +
  // consolidate (entrée). Le handler de drag (SortableJS) sera ajouté en session VISUELLE (avec P2),
  // et posera sessionStorage['wama_focus_card'] sur l'id déplacé pour le repérer après reload.

  // ── Batch duplicate ───────────────────────────────────────────────────────
  document.addEventListener('click', function(e) {
    const btn = e.target.closest('.batch-duplicate-btn');
    if (!btn) return;
    const batchId = btn.dataset.batchId;
    const url = config.batchDuplicateUrlTemplate.replace('/0/', `/${batchId}/`);
    fetch(url, {method: 'POST', headers: csrfHeaders()})
      .then(r => r.json())
      .then(data => {
        if (data.success) {
          showToast('Batch dupliqué', 'success');
          setTimeout(() => location.reload(), 600);
        }
      })
      .catch(() => showToast('Erreur lors de la duplication', 'danger'));
  });

  function initUpload() {
    if (!fileInput) return;
    fileInput.addEventListener('change', function () {
      if (!this.files.length) return;
      handleFiles(this.files);
      fileInput.value = '';
    });
  }

  function initDragDrop() {
    const dropZone = document.getElementById('dropZoneTranscriber');
    const browseBtn = document.getElementById('transcriber-browse-btn');
    if (!dropZone || !fileInput) return;

    dropZone.addEventListener('click', (e) => { if (e.target !== browseBtn) fileInput.click(); });
    if (browseBtn) browseBtn.addEventListener('click', (e) => { e.stopPropagation(); fileInput.click(); });
    dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('drag-over'); });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
    dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropZone.classList.remove('drag-over');
      if (e.dataTransfer.files.length > 0) handleFiles(e.dataTransfer.files);
    });
  }

  function initYoutube() {
    const youtubeUrl = document.getElementById('youtubeUrl');
    const youtubeBtn = document.getElementById('youtubeSubmitBtn');
    if (!youtubeUrl || !youtubeBtn) return;

    youtubeBtn.addEventListener('click', async () => {
      const url = youtubeUrl.value.trim();
      if (!url) { showToast('Veuillez entrer une URL YouTube', 'warning'); return; }

      youtubeBtn.disabled = true;
      youtubeBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Téléchargement...';

      try {
        const body = new FormData();
        body.append('youtube_url', url);
        _appendPanelParams(body);
        const response = await fetch(config.uploadYoutubeUrl, { method: 'POST', headers: csrfHeaders(), body });
        const data = await response.json();
        if (data.error) throw new Error(data.error);
        youtubeUrl.value = '';
        if (window.WamaFM) WamaFM.uploaded();
        // L'élément arrive en zone de staging (DRAFT) → recharge (rendu serveur).
        location.reload();
      } catch (error) {
        showToast(`Erreur YouTube: ${error.message}`, 'danger');
      } finally {
        youtubeBtn.disabled = false;
        youtubeBtn.innerHTML = '<i class="fas fa-download"></i> Télécharger & Transcrire';
      }
    });

    youtubeUrl.addEventListener('keypress', (e) => { if (e.key === 'Enter') youtubeBtn.click(); });
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

    // Update card class
    card.className = 'synthesis-card' + ({
      RUNNING: ' processing', SUCCESS: ' success', FAILURE: ' error'
    }[status] || '');
    card.dataset.status = status;

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
      else if (status === 'PENDING') { st.className = 'card-state text-white-50'; st.textContent = 'En attente'; }
      else if (status === 'FAILURE') { st.className = 'card-state text-danger'; st.innerHTML = '<i class="fas fa-triangle-exclamation"></i> Échec'; }
      else { st.className = 'card-state'; st.textContent = ''; }
    }

    // Update live transcription display
    updateLiveTranscriptionFromQueue(id, status, data.partial_text);

    // Fin de process : agir UNIQUEMENT sur un statut terminal réel (pas sur
    // progress>=100 seul, qui peut précéder le passage en SUCCESS).
    if (status === 'SUCCESS') {
      stopPolling(id);
      if (window.WamaFM) WamaFM.processed();  // sortie créée → refresh filemanager
      // Reload → rendu serveur complet : preview compacte, options à jour,
      // onglet cohérence, barre à 100 %. Évite le « revert » des options.
      setTimeout(() => location.reload(), 300);
    } else if (status === 'FAILURE') {
      stopPolling(id);
      refreshCard(id);
    }

    updateDownloadAllState();
  }

  // Card RENDUE SERVEUR — source unique : partial _transcript_card.html via
  // transcriber:card_html. Remplace rebuildActions (3e copie du markup d'actions +
  // save/restore manuel de 9 data-attributes) — audit A2-10.
  function refreshCard(id) {
    fetch(WamaApp.getUrl(window.TRANSCRIBER_APP.cardHtmlUrlTemplate, id))
      .then(r => { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(html => {
        const card = document.querySelector(`.synthesis-card[data-id="${id}"]`);
        if (card) card.outerHTML = html;
        else document.getElementById('transcriptQueue')?.insertAdjacentHTML('afterbegin', html);
      })
      .catch(() => {});
  }

  // ======================================================================
  // Card actions
  // ======================================================================
  function bindCardActions(scope) {
    const root = scope || document;

    // Bouton de cycle commun (délégué, lié une fois par card ; survit aux rebuilds d'actions).
    if (window.WamaCycleButton) {
      WamaCycleButton.wire(root, { start: (id) => handleStart(id), stop: (id) => handleStop(id) });
    }
    // Repli legacy si la brique n'est pas chargée.
    root.querySelectorAll('.start-btn').forEach(btn => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => handleStart(btn.dataset.id));
    });

    root.querySelectorAll('.settings-btn').forEach(btn => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => openSettingsModal(btn));
    });

    root.querySelectorAll('.delete-btn').forEach(btn => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => handleDelete(btn.dataset.id));
    });

    root.querySelectorAll('.duplicate-btn').forEach(btn => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => handleDuplicate(btn.dataset.id));
    });
  }

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

  function handleStart(id) {
    const card = queueContainer.querySelector(`.synthesis-card[data-id="${id}"]`);
    // Relance PENDANT le traitement (modale « Enregistrer & démarrer ») : on stoppe d'abord pour
    // éviter le 409 « déjà en cours », puis on relance avec les params à jour.
    if (card && (card.dataset.status || '').toUpperCase() === 'RUNNING') {
      card.dataset.status = 'PENDING';   // évite la récursion + reflète l'arrêt imminent
      fetch(getUrl(config.stopUrlTemplate, id), {
        method: 'POST', headers: csrfHeaders({ 'Content-Type': 'application/json' }), body: '{}',
      }).then(() => doStart(id, card)).catch(() => doStart(id, card));
      return;
    }
    doStart(id, card);
  }

  function doStart(id, card) {
    const url = getUrl(config.startUrlTemplate, id);
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
          card.className = 'synthesis-card processing';
          const badge = card.querySelector('.status-badge');
          if (badge) { badge.textContent = 'RUNNING'; badge.className = 'badge status-badge bg-warning'; }
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

  function handleDelete(id) {
    if (!confirm('Supprimer cette transcription ?')) return;

    const url = getUrl(config.deleteUrlTemplate, id);
    fetch(url, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({}),
    })
      .then(r => r.json())
      .then(data => {
        if (!data.deleted) throw new Error('Suppression impossible');
        // Élément issu d'un batch : le total/affichage du batch change (et un batch réduit à 1
        // redevient une card simple) → recharger pour re-rendre proprement le groupe.
        if (data.batch_changed) { if (window.WamaFM) WamaFM.deleted(); location.reload(); return; }
        const card = queueContainer.querySelector(`.synthesis-card[data-id="${id}"]`);
        if (card) card.remove();
        if (_inspector && String(id) === String(_inspector.state().itemId)) _inspector.deselect();  // évite des actions inspecteur orphelines
        stopPolling(id);
        insertEmptyStateIfNeeded();
        updateDownloadAllState();
        if (window.WamaFM) WamaFM.deleted();  // fichier supprimé → refresh filemanager
      })
      .catch(err => showToast(err.message || 'Erreur lors de la suppression', 'danger'));
  }

  function handleDuplicate(id) {
    const url = getUrl(config.duplicateUrlTemplate, id);
    fetch(url, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({}),
    })
      .then(r => r.json())
      .then(data => {
        if (!data.duplicated) throw new Error('Duplication impossible');
        // Focus la card dupliquée après rechargement (WamaQueue.focusFromSession) — la repérer
        // facilement, surtout sortie/isolée d'un batch ou si elle n'atterrit pas en tête.
        try { sessionStorage.setItem('wama_focus_card', '.synthesis-card[data-id="' + data.duplicated + '"]'); } catch (e) {}
        location.reload();
      })
      .catch(err => showToast(err.message || 'Erreur lors de la duplication', 'danger'));
  }

  // ======================================================================
  // Settings modal
  // ======================================================================
  // Mode batch de la modale de paramètres : la même modale individuelle est
  // réutilisée pour le batch (pas de modale dédiée). _settingsBatchId != null
  // → la sauvegarde s'applique à TOUS les items du batch (conventions §9.8/§9.9).
  let _settingsBatchId = null;

  document.addEventListener('click', function (e) {
    const bbtn = e.target.closest('.batch-settings-btn');
    if (!bbtn) return;
    openBatchSettingsModal(bbtn);
  });

  function openBatchSettingsModal(btn) {
    const group = btn.closest('.batch-group');
    const firstItemBtn = group ? group.querySelector('.settings-btn') : null;
    if (firstItemBtn) {
      openSettingsModal(firstItemBtn);   // pré-remplit avec les réglages du 1er élément
    } else {
      const m = document.getElementById('settingsModal');
      if (m) new bootstrap.Modal(m).show();
    }
    _settingsBatchId = btn.dataset.batchId;   // bascule en mode batch APRÈS le prefill
    const title = document.querySelector('#settingsModal .modal-title');
    if (title) title.textContent = 'Paramètres du batch — appliqués à tous les éléments';
  }

  function openSettingsModal(btn) {
    const modal = document.getElementById('settingsModal');
    if (!modal) return;
    _settingsBatchId = null;                   // mode individuel par défaut
    const _t = modal.querySelector('.modal-title');
    if (_t) _t.textContent = 'Paramètres de transcription';

    document.getElementById('settingsTranscriptId').value = btn.dataset.id;
    // Population via le schéma commun (WamaParams) : gère range (+ affichage) et show/hide
    // conditionnel du bloc résumé. Mêmes IDs/noms qu'avant (dom_id scopé context 'item').
    if (window.WamaParams) {
      WamaParams.apply(document.getElementById('settingsParams'), {
        backend: btn.dataset.backend || 'auto',
        hotwords: btn.dataset.hotwords || '',
        preprocess_audio: btn.dataset.preprocess === 'true',
        enable_diarization: btn.dataset.diarization !== 'false',
        temperature: parseFloat(btn.dataset.temperature) || 0,
        max_tokens: parseInt(btn.dataset.maxTokens) || 32768,
        generate_summary: btn.dataset.generateSummary === 'true',
        summary_type: btn.dataset.summaryType || 'structured',
        verify_coherence: btn.dataset.verifyCoherence === 'true',
      });
    }

    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();
  }

  // Toggle summary type group visibility — both global panel and per-transcript modal
  document.addEventListener('change', function(e) {
    if (e.target && e.target.id === 'settingsGenerateSummary') {
      const group = document.getElementById('summaryTypeGroup');
      if (group) group.style.display = e.target.checked ? 'block' : 'none';
    }
    if (e.target && e.target.id === 'globalGenerateSummary') {
      const group = document.getElementById('globalSummaryTypeGroup');
      if (group) group.style.display = e.target.checked ? 'block' : 'none';
    }
  });

  function saveSettings(andStart) {
    const id = document.getElementById('settingsTranscriptId').value;
    if (!id) return;

    const summaryTypeEl = document.querySelector('input[name="summary_type"]:checked');

    const payload = {
      backend: document.getElementById('settingsBackend').value,
      hotwords: document.getElementById('settingsHotwords').value,
      preprocess_audio: document.getElementById('settingsPreprocess').checked,
      enable_diarization: document.getElementById('settingsDiarization').checked,
      temperature: 0,        // réglages retirés de l'UI (ASR = reproductibilité) → valeurs fixes
      max_tokens: 32768,
      generate_summary: document.getElementById('settingsGenerateSummary')?.checked || false,
      summary_type: summaryTypeEl ? summaryTypeEl.value : 'structured',
      verify_coherence: document.getElementById('settingsVerifyCoherence')?.checked || false,
    };

    // Mode batch : applique à tous les items + relance éventuelle du batch.
    if (_settingsBatchId) {
      const bid = _settingsBatchId;
      _settingsBatchId = null;
      fetch(getUrl(config.batchUpdateUrlTemplate, bid), {
        method: 'POST',
        headers: csrfHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(payload),
      })
        .then(r => r.json())
        .then(() => {
          const m = bootstrap.Modal.getInstance(document.getElementById('settingsModal'));
          if (m) m.hide();
          if (andStart) {
            fetch(getUrl(config.batchStartUrlTemplate, bid), { method: 'POST', headers: csrfHeaders() })
              .finally(() => location.reload());
          } else {
            location.reload();
          }
        })
        .catch(() => showToast('Erreur lors de la mise à jour du batch', 'danger'));
      return;
    }

    const url = getUrl(config.settingsUrlTemplate, id);
    fetch(url, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    })
      .then(r => r.json())
      .then(data => {
        // Close modal
        const modal = bootstrap.Modal.getInstance(document.getElementById('settingsModal'));
        if (modal) modal.hide();

        // Update card's data-attributes and options display
        const card = queueContainer.querySelector(`.synthesis-card[data-id="${id}"]`);
        if (card) {
          card.dataset.backend = payload.backend;
          card.dataset.hotwords = payload.hotwords;
          card.dataset.preprocess = payload.preprocess_audio ? 'true' : 'false';
          card.dataset.diarization = payload.enable_diarization ? 'true' : 'false';
          card.dataset.temperature = payload.temperature;
          card.dataset.maxTokens = payload.max_tokens;
          card.dataset.generateSummary = payload.generate_summary ? 'true' : 'false';
          card.dataset.summaryType = payload.summary_type;
          card.dataset.verifyCoherence = payload.verify_coherence ? 'true' : 'false';

          const settingsBtn = card.querySelector('.settings-btn');
          if (settingsBtn) {
            settingsBtn.dataset.backend = payload.backend;
            settingsBtn.dataset.hotwords = payload.hotwords;
            settingsBtn.dataset.preprocess = payload.preprocess_audio ? 'true' : 'false';
            settingsBtn.dataset.diarization = payload.enable_diarization ? 'true' : 'false';
            settingsBtn.dataset.temperature = payload.temperature;
            settingsBtn.dataset.maxTokens = payload.max_tokens;
            settingsBtn.dataset.generateSummary = payload.generate_summary ? 'true' : 'false';
            settingsBtn.dataset.summaryType = payload.summary_type;
            settingsBtn.dataset.verifyCoherence = payload.verify_coherence ? 'true' : 'false';
          }

          // Update options column display
          const optionsCol = card.querySelectorAll('.col-md-2')[0];
          if (optionsCol) {
            let optHtml = `<small><i class="fas fa-microchip"></i> ${escapeHtml(payload.backend)}<br>`;
            if (payload.hotwords) optHtml += `<i class="fas fa-tags"></i> ${escapeHtml(payload.hotwords.substring(0, 20))}${payload.hotwords.length > 20 ? '...' : ''}<br>`;
            if (payload.enable_diarization) optHtml += `<i class="fas fa-users"></i> Diarisation<br>`;
            if (payload.generate_summary) optHtml += `<i class="fas fa-file-lines"></i> Résumé<br>`;
            if (payload.verify_coherence) optHtml += `<i class="fas fa-spell-check"></i> Cohérence`;
            optHtml += '</small>';
            optionsCol.innerHTML = optHtml;
          }
        }

        if (andStart) handleStart(id);
      })
      .catch(err => showToast(err.message || 'Erreur lors de la sauvegarde', 'danger'));
  }

  // ======================================================================
  // Result modal — tabbed interface
  // ======================================================================

  const SPEAKER_COLORS = [
    '#4e79a7', '#f28e2b', '#e15759', '#76b7b2',
    '#59a14f', '#edc948', '#b07aa1', '#ff9da7',
    '#9c755f', '#bab0ac',
  ];
  const speakerColorMap = {};
  let speakerColorIdx = 0;

  function getSpeakerColor(speaker) {
    if (!speakerColorMap[speaker]) {
      speakerColorMap[speaker] = SPEAKER_COLORS[speakerColorIdx % SPEAKER_COLORS.length];
      speakerColorIdx++;
    }
    return speakerColorMap[speaker];
  }

  function renderDiarisation(segments) {
    const container = document.getElementById('diarisationContent');
    if (!container) return;

    const withSpeakers = segments.filter(s => s.speaker_id);
    if (!withSpeakers.length) {
      container.innerHTML = '<p class="text-muted text-center py-4">Aucune donnée de diarisation disponible.</p>';
      return;
    }

    // Reset color map for this transcript
    Object.keys(speakerColorMap).forEach(k => delete speakerColorMap[k]);
    speakerColorIdx = 0;

    let html = '';
    for (const seg of withSpeakers) {
      const color = getSpeakerColor(seg.speaker_id);
      const timeRange = seg.time_range || `${seg.start_time?.toFixed(1)}s → ${seg.end_time?.toFixed(1)}s`;
      html += `
        <div class="d-flex align-items-start mb-2 px-1">
          <div style="min-width: 120px;">
            <span class="badge me-1" style="background-color:${color}; color:#fff; font-size:0.75rem;">${escapeHtml(seg.speaker_id)}</span>
            <small class="text-muted">${escapeHtml(timeRange)}</small>
          </div>
          <div class="ms-2 text-light" style="font-size:14px; line-height:1.5;">${escapeHtml(seg.text || '')}</div>
        </div>`;
    }
    container.innerHTML = html;
  }

  function renderResume(data) {
    const resumeEl = document.getElementById('resumeContent');
    const tabBtn = document.getElementById('tab-resume-btn');
    if (!resumeEl || !tabBtn) return;

    if (!data.summary) {
      tabBtn.style.display = 'none';
      return;
    }

    tabBtn.style.display = '';

    // Convert markdown-like content to simple HTML
    let html = data.summary
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/### (.+)/g, '<h6 class="text-info mt-3 mb-1">$1</h6>')
      .replace(/## (.+)/g, '<h5 class="text-warning mt-3 mb-2">$1</h5>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/^- (.+)$/gm, '<li>$1</li>')
      .replace(/(<li>.*<\/li>\n?)+/g, m => `<ul>${m}</ul>`)
      .replace(/\n\n/g, '<br><br>')
      .replace(/\n/g, '<br>');

    // Key points
    if (data.key_points && data.key_points.length) {
      html += '<h6 class="text-info mt-3">Points clés</h6><ul>';
      data.key_points.forEach(p => { html += `<li>${escapeHtml(String(p))}</li>`; });
      html += '</ul>';
    }

    // Action items
    if (data.action_items && data.action_items.length) {
      html += '<h6 class="text-warning mt-3">Actions à mener</h6><ul>';
      data.action_items.forEach(a => { html += `<li>${escapeHtml(String(a))}</li>`; });
      html += '</ul>';
    }

    resumeEl.innerHTML = html;
    setWordCount('wc-resume', data.summary || '');
  }

  function renderCoherence(data, originalText) {
    const container = document.getElementById('coherenceContent');
    const tabBtn = document.getElementById('tab-coherence-btn');
    if (!container || !tabBtn) return;

    if (data.coherence_score === null || data.coherence_score === undefined) {
      tabBtn.style.display = 'none';
      return;
    }

    tabBtn.style.display = '';

    const score = data.coherence_score;
    const scoreColor = score >= 80 ? 'success' : score >= 50 ? 'warning' : 'danger';

    let notesHtml = '';
    if (data.coherence_notes) {
      const notes = data.coherence_notes.split('\n').filter(l => l.trim());
      notesHtml = '<ul class="mt-2">' + notes.map(n => `<li class="text-light small">${escapeHtml(n)}</li>`).join('') + '</ul>';
    }

    let sideBySide = '';
    if (data.coherence_suggestion) {
      sideBySide = `
        <div class="row mt-3">
          <div class="col-md-6">
            <div class="card" style="background:#1e1e1e; border:1px solid #495057;">
              <div class="card-header py-1 small text-muted">Texte original</div>
              <div class="card-body p-2">
                <pre style="color:#d4d4d4; white-space:pre-wrap; font-size:13px; max-height:300px; overflow-y:auto; margin:0;">${escapeHtml(originalText || '')}</pre>
              </div>
            </div>
          </div>
          <div class="col-md-6">
            <div class="card" style="background:#1e2820; border:1px solid #2ea043;">
              <div class="card-header py-1 small text-muted">Correction proposée</div>
              <div class="card-body p-2">
                <pre style="color:#7ee787; white-space:pre-wrap; font-size:13px; max-height:300px; overflow-y:auto; margin:0;">${escapeHtml(data.coherence_suggestion)}</pre>
              </div>
            </div>
          </div>
        </div>`;
    }

    container.innerHTML = `
      <div class="d-flex align-items-center mb-2">
        <span class="badge bg-${scoreColor} fs-5 me-3">${score}/100</span>
        <span class="text-light">Score de cohérence</span>
      </div>
      ${notesHtml}
      ${sideBySide}`;
    setWordCount('wc-coherence', data.coherence_suggestion || originalText || '');
  }

  function openResultModal(id) {
    const modal = document.getElementById('resultModal');
    if (!modal) return;

    const resultText = document.getElementById('resultText');
    const title = document.getElementById('resultModalTitle');
    const dlBtn = document.getElementById('resultDownloadBtn');
    const srtBtn = document.getElementById('resultSrtBtn');

    if (title) title.textContent = `Transcription #${id}`;
    if (resultText) resultText.textContent = 'Chargement...';
    if (dlBtn) dlBtn.href = getUrl(config.downloadUrlTemplate, id) + '?format=txt';
    if (srtBtn) srtBtn.href = getUrl(config.downloadUrlTemplate, id) + '?format=srt';

    // Reset tabs visibility
    const tabResumeBtn = document.getElementById('tab-resume-btn');
    const tabCoherenceBtn = document.getElementById('tab-coherence-btn');
    if (tabResumeBtn) tabResumeBtn.style.display = 'none';
    if (tabCoherenceBtn) tabCoherenceBtn.style.display = 'none';

    // Reset diarisation
    const diarEl = document.getElementById('diarisationContent');
    if (diarEl) diarEl.innerHTML = '<p class="text-muted text-center py-3"><i class="fas fa-spinner fa-spin"></i> Chargement...</p>';

    // Activate transcription tab
    const transcriptionTab = document.getElementById('tab-transcription-btn');
    if (transcriptionTab) {
      const bsTab = new bootstrap.Tab(transcriptionTab);
      bsTab.show();
    }

    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();

    // 1. Fetch progress data (text + summary + coherence)
    fetch(getUrl(config.progressUrlTemplate, id))
      .then(r => r.json())
      .then(data => {
        if (resultText) {
          resultText.textContent = data.text || data.partial_text || '(Aucun texte disponible)';
          setWordCount('wc-transcription', data.text || data.partial_text || '');
        }
        renderResume(data);
        renderCoherence(data, data.text || data.partial_text || '');
      })
      .catch(() => {
        if (resultText) resultText.textContent = 'Erreur de chargement';
      });

    // 2. Fetch segments for diarisation tab
    if (config.segmentsUrlTemplate) {
      fetch(getUrl(config.segmentsUrlTemplate, id))
        .then(r => r.json())
        .then(data => {
          renderDiarisation(data.segments || []);
        })
        .catch(() => {
          const diarEl2 = document.getElementById('diarisationContent');
          if (diarEl2) diarEl2.innerHTML = '<p class="text-muted text-center py-4">Erreur de chargement des segments.</p>';
        });
    }
  }

  // ======================================================================
  // Polling
  // ======================================================================
  // Polling de progression — délégué à WamaApp.Poller (comportement identique :
  // résilient aux erreurs réseau transitoires, updateCard protégé par try/catch).
  function startPolling(id) { _poller.start(id); }
  function stopPolling(id) { _poller.stop(id); }

  // ======================================================================
  // Empty state
  // ======================================================================
  // État vide — délégué à WamaApp.emptyState (instance `_empty` créée en tête).
  function removeEmptyState() { _empty.remove(); }
  function insertEmptyStateIfNeeded() { _empty.insertIfNeeded(); }

  // ======================================================================
  // Bulk actions
  // ======================================================================
  function initBulkActions() {
    if (startProcessBtn) startProcessBtn.addEventListener('click', handleStartAll);
    if (clearAllBtn) clearAllBtn.addEventListener('click', handleClearAll);
    if (downloadAllBtn) {
      // Bulk download = late-binding export: let the user pick the format (txt/srt/pdf/docx),
      // mirroring the per-item download dropdown. The shared queue-actions partial renders a
      // plain button; we wrap it into a Bootstrap dropdown here (transcriber is master-based).
      const downloadAllUrl = config.startAllUrl.replace('start_all', 'download_all');
      const wrap = document.createElement('div');
      wrap.className = 'dropdown d-inline-block';
      downloadAllBtn.parentNode.insertBefore(wrap, downloadAllBtn);
      wrap.appendChild(downloadAllBtn);
      downloadAllBtn.classList.add('dropdown-toggle');
      downloadAllBtn.setAttribute('type', 'button');
      downloadAllBtn.setAttribute('data-bs-toggle', 'dropdown');
      downloadAllBtn.setAttribute('aria-expanded', 'false');
      const menu = document.createElement('ul');
      menu.className = 'dropdown-menu';
      [['txt', 'Texte (.txt)'], ['srt', 'Sous-titres (.srt)'], ['pdf', 'PDF (.pdf)'], ['docx', 'Word (.docx)']]
        .forEach(([fmt, label]) => {
          const li = document.createElement('li');
          const a = document.createElement('a');
          a.className = 'dropdown-item';
          a.href = '#';
          a.textContent = label;
          a.addEventListener('click', (e) => {
            e.preventDefault();
            window.location.href = downloadAllUrl + '?format=' + fmt;
          });
          li.appendChild(a);
          menu.appendChild(li);
        });
      wrap.appendChild(menu);
    }
    if (preprocessToggle) {
      preprocessToggle.checked = preprocessEnabled;
      preprocessToggle.addEventListener('change', () => {
        preprocessEnabled = preprocessToggle.checked;
        // Inspecteur : si un élément/batch est inspecté, on l'édite sans toucher le défaut ;
        // sinon on persiste la préférence globale de prétraitement.
        const st = _inspector ? _inspector.state() : {};
        if (!st.itemId && !st.batchId) persistPreprocessingPreference(preprocessEnabled);
        savePanelSettings();
      });
    }

    // Auto-save all other panel settings on change
    const panelBackendSel = document.getElementById('backendSelect');
    const panelHotwordsIn = document.getElementById('hotwordsInput');
    const panelDiarToggle = document.getElementById('diarizationToggle');
    const panelGenSumm    = document.getElementById('globalGenerateSummary');
    const panelVerifCoh   = document.getElementById('globalVerifyCoherence');
    if (panelBackendSel) panelBackendSel.addEventListener('change', savePanelSettings);
    if (panelHotwordsIn) panelHotwordsIn.addEventListener('blur', savePanelSettings);
    if (panelDiarToggle) panelDiarToggle.addEventListener('change', savePanelSettings);
    if (panelGenSumm)    panelGenSumm.addEventListener('change', savePanelSettings);
    if (panelVerifCoh)   panelVerifCoh.addEventListener('change', savePanelSettings);
    const panelTemp = document.getElementById('panelTemperature');
    const panelMaxTok = document.getElementById('panelMaxTokens');
    if (panelTemp)   panelTemp.addEventListener('change', savePanelSettings);
    if (panelMaxTok) panelMaxTok.addEventListener('change', savePanelSettings);
    document.querySelectorAll('input[name="globalSummaryType"]').forEach(r =>
      r.addEventListener('change', savePanelSettings)
    );

    // Settings modal buttons
    const saveBtn = document.getElementById('saveSettingsBtn');
    const saveStartBtn = document.getElementById('saveAndStartBtn');
    if (saveBtn) saveBtn.addEventListener('click', () => saveSettings(false));
    if (saveStartBtn) saveStartBtn.addEventListener('click', () => saveSettings(true));

    // Reset button
    const resetBtn = document.getElementById('resetOptions');
    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        const backendEl = document.getElementById('backendSelect');
        if (backendEl) backendEl.value = 'auto';

        const hotwordsEl = document.getElementById('hotwordsInput');
        if (hotwordsEl) hotwordsEl.value = '';

        const preprocessEl = document.getElementById('preprocessingToggle');
        if (preprocessEl) { preprocessEl.checked = false; preprocessEnabled = false; }

        const diarizationEl = document.getElementById('diarizationToggle');
        if (diarizationEl) diarizationEl.checked = false;

        const genSummaryEl = document.getElementById('globalGenerateSummary');
        if (genSummaryEl) {
          genSummaryEl.checked = false;
          genSummaryEl.dispatchEvent(new Event('change'));   // WamaParams masque le bloc résumé
        }

        const summTypeEl = document.querySelector('input[name="globalSummaryType"][value="structured"]');
        if (summTypeEl) summTypeEl.checked = true;

        const verifCoherEl = document.getElementById('globalVerifyCoherence');
        if (verifCoherEl) verifCoherEl.checked = false;

        savePanelSettings();
      });
    }
  }

  function handleStartAll() {
    if (!config.startAllUrl) return;
    startProcessBtn.disabled = true;
    fetch(config.startAllUrl, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({}),
    })
      .then(r => r.json())
      .then(data => {
        const started = data.started_ids || [];
        if (!started.length) { showToast('Aucune transcription à démarrer.', 'info'); return; }
        started.forEach(id => startPolling(id));
        // Reload to get fresh card states
        window.location.reload();
      })
      .catch(err => showToast(err.message || 'Erreur', 'danger'))
      .finally(() => { startProcessBtn.disabled = false; });
  }

  function handleClearAll() {
    if (!config.clearUrl) return;
    if (!confirm('Supprimer toutes les transcriptions ?')) return;

    clearAllBtn.disabled = true;
    fetch(config.clearUrl, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({}),
    })
      .then(r => r.json())
      .then(() => {
        if (queueContainer) {
          queueContainer.querySelectorAll('.synthesis-card').forEach(c => c.remove());
        }
        _poller.stopAll();
        insertEmptyStateIfNeeded();
        updateDownloadAllState();
        if (window.WamaFM) WamaFM.deleted();  // fichiers supprimés → refresh filemanager
      })
      .catch(err => showToast(err.message || 'Erreur', 'danger'))
      .finally(() => { clearAllBtn.disabled = false; });
  }

  function updateDownloadAllState() {
    if (!downloadAllBtn || !queueContainer) return;
    const hasSuccess = !!queueContainer.querySelector('.synthesis-card[data-status="SUCCESS"]');
    downloadAllBtn.disabled = !hasSuccess;
  }

  function persistPreprocessingPreference(enabled) {
    const endpoint = config.preprocessingUrl || toggleDatasetUrl;
    if (!endpoint) return;
    fetch(endpoint, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ enabled }),
    }).catch(() => {
      if (preprocessToggle) preprocessToggle.checked = !enabled;
    });
  }

  // ======================================================================
  // Inspecteur (niveau 2) — le volet droit reflète la card sélectionnée
  // ======================================================================
  let _inspector = null;   // instance WamaInspector (module commun) — créée dans initInspector

  function _panelReadValues() {
    const st = document.querySelector('input[name="globalSummaryType"]:checked');
    const e = id => document.getElementById(id);
    return {
      backend:            e('backendSelect') ? e('backendSelect').value : 'auto',
      hotwords:           e('hotwordsInput') ? e('hotwordsInput').value : '',
      preprocess_audio:   e('preprocessingToggle') ? e('preprocessingToggle').checked : false,
      enable_diarization: e('diarizationToggle') ? e('diarizationToggle').checked : true,
      generate_summary:   e('globalGenerateSummary') ? e('globalGenerateSummary').checked : false,
      summary_type:       st ? st.value : 'structured',
      verify_coherence:   e('globalVerifyCoherence') ? e('globalVerifyCoherence').checked : false,
      temperature:        e('panelTemperature') ? (parseFloat(e('panelTemperature').value) || 0) : 0,
      max_tokens:         e('panelMaxTokens') ? (parseInt(e('panelMaxTokens').value) || 32768) : 32768,
    };
  }

  function _panelApplyValues(s) {
    const e = id => document.getElementById(id);
    if (e('backendSelect') && s.backend) e('backendSelect').value = s.backend;
    if (e('hotwordsInput')) e('hotwordsInput').value = s.hotwords || '';
    if (e('preprocessingToggle')) { e('preprocessingToggle').checked = !!s.preprocess_audio; preprocessEnabled = !!s.preprocess_audio; }
    if (e('diarizationToggle')) e('diarizationToggle').checked = s.enable_diarization !== false;
    if (e('globalGenerateSummary')) {
      e('globalGenerateSummary').checked = !!s.generate_summary;
      // WamaParams pilote le show/hide du bloc résumé via [data-show-if] : déclenche son listener.
      e('globalGenerateSummary').dispatchEvent(new Event('change'));
    }
    const stEl = document.querySelector(`input[name="globalSummaryType"][value="${s.summary_type || 'structured'}"]`);
    if (stEl) stEl.checked = true;
    if (e('globalVerifyCoherence')) e('globalVerifyCoherence').checked = !!s.verify_coherence;
    if (e('panelTemperature')) {
      const t = (s.temperature != null) ? s.temperature : 0;
      e('panelTemperature').value = t;
      const _trow = e('panelTemperature') ? e('panelTemperature').closest('.wama-param') : null;
      const tv = _trow ? _trow.querySelector('.wama-range-val') : null; if (tv) tv.textContent = t;
    }
    if (e('panelMaxTokens')) e('panelMaxTokens').value = s.max_tokens || 32768;
  }

  function _cardSettings(card) {
    const b = card.querySelector('.settings-btn');
    const d = b ? b.dataset : card.dataset;
    return {
      backend: d.backend || 'auto',
      hotwords: d.hotwords || '',
      preprocess_audio: d.preprocess === 'true',
      enable_diarization: d.diarization !== 'false',
      generate_summary: d.generateSummary === 'true',
      summary_type: d.summaryType || 'structured',
      verify_coherence: d.verifyCoherence === 'true',
      temperature: parseFloat(d.temperature) || 0,
      max_tokens: parseInt(d.maxTokens) || 32768,
    };
  }

  // Actions de la card inspectée (callback WamaInspector) : clone des boutons de la card + rebind.
  function _renderItemActions(host, card) {
    const ga = card.querySelector('.btn-group-actions');
    const id = card.dataset.id;
    host.innerHTML =
      '<div class="small text-white-50 mb-1"><i class="fas fa-crosshairs text-info"></i> Actions — élément #' + id + '</div>' +
      '<div class="btn-group-actions d-flex flex-wrap gap-1">' + (ga ? ga.innerHTML : '') + '</div>' +
      '<hr class="border-secondary my-2">';
    // Les boutons clonés héritent de data-bound="1" → on le retire pour réautoriser le binding.
    host.querySelectorAll('[data-bound]').forEach(function (b) { delete b.dataset.bound; });
    bindCardActions(host);
  }

  // Actions batch autonomes (callback WamaInspector) — pas de clone : les handlers batch
  // existants dépendent de l'arborescence DOM, on (re)construit donc des boutons dédiés.
  function _renderBatchActions(host, batchId) {
    const dl = (fmt) => getUrl(config.batchDownloadUrlTemplate, batchId) + '?fmt=' + fmt;
    host.innerHTML =
      '<div class="small text-white-50 mb-1"><i class="fas fa-layer-group text-info"></i> Actions — batch #' + batchId + '</div>' +
      '<div class="d-flex flex-wrap gap-1">' +
        '<button class="btn btn-sm btn-success" id="inspBatchStart" title="Démarrer tout le batch"><i class="fas fa-play"></i></button>' +
        '<div class="dropdown d-inline-block"><button class="btn btn-sm btn-outline-info dropdown-toggle" data-bs-toggle="dropdown" title="Télécharger (ZIP)"><i class="fas fa-download"></i></button>' +
          '<ul class="dropdown-menu dropdown-menu-dark dropdown-menu-end">' +
            '<li><a class="dropdown-item" href="' + dl('txt') + '">Tout en TXT</a></li>' +
            '<li><a class="dropdown-item" href="' + dl('srt') + '">Tout en SRT</a></li>' +
            '<li><a class="dropdown-item" href="' + dl('pdf') + '">Tout en PDF</a></li>' +
            '<li><a class="dropdown-item" href="' + dl('docx') + '">Tout en DOCX</a></li>' +
          '</ul></div>' +
        '<button class="btn btn-sm btn-outline-info" id="inspBatchDup" title="Dupliquer le batch"><i class="fas fa-copy"></i></button>' +
        '<button class="btn btn-sm btn-outline-danger" id="inspBatchDel" title="Supprimer le batch"><i class="fas fa-trash"></i></button>' +
      '</div><hr class="border-secondary my-2">';
    const post = (tpl) => fetch(getUrl(tpl, batchId), { method: 'POST', headers: csrfHeaders() });
    const s = document.getElementById('inspBatchStart');
    if (s) s.addEventListener('click', () => post(config.batchStartUrlTemplate).then(() => location.reload()).catch(() => {}));
    const d = document.getElementById('inspBatchDup');
    if (d) d.addEventListener('click', () => post(config.batchDuplicateUrlTemplate).then(() => location.reload()).catch(() => {}));
    const x = document.getElementById('inspBatchDel');
    if (x) x.addEventListener('click', () => {
      if (confirm('Supprimer ce batch et toutes ses transcriptions ?')) post(config.batchDeleteUrlTemplate).then(() => location.reload()).catch(() => {});
    });
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
      .then(() => {
        // Garde la card synchronisée (data-* du bouton paramètres)
        if (card) {
          const b = card.querySelector('.settings-btn');
          if (b) {
            b.dataset.backend = payload.backend;
            b.dataset.hotwords = payload.hotwords;
            b.dataset.preprocess = payload.preprocess_audio ? 'true' : 'false';
            b.dataset.diarization = payload.enable_diarization ? 'true' : 'false';
            b.dataset.generateSummary = payload.generate_summary ? 'true' : 'false';
            b.dataset.summaryType = payload.summary_type;
            b.dataset.verifyCoherence = payload.verify_coherence ? 'true' : 'false';
            b.dataset.temperature = payload.temperature;
            b.dataset.maxTokens = payload.max_tokens;
          }
        }
      })
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

  // Sauvegarde des valeurs par défaut (niveau file, rien d'inspecté).
  function saveGlobalSettings() {
    if (!config.saveUserSettingsUrl) return;
    const backendSel  = document.getElementById('backendSelect');
    const hotwordsIn  = document.getElementById('hotwordsInput');
    const diarEl      = document.getElementById('diarizationToggle');
    const genSummEl   = document.getElementById('globalGenerateSummary');
    const summTypeEl  = document.querySelector('input[name="globalSummaryType"]:checked');
    const verifEl     = document.getElementById('globalVerifyCoherence');
    const payload = {
      backend:               backendSel ? backendSel.value  : 'auto',
      hotwords:              hotwordsIn ? hotwordsIn.value  : '',
      enable_diarization:    diarEl     ? diarEl.checked    : true,
      preprocessing_enabled: preprocessEnabled,
      generate_summary:      genSummEl  ? genSummEl.checked : false,
      summary_type:          summTypeEl ? summTypeEl.value  : 'structured',
      verify_coherence:      verifEl    ? verifEl.checked   : false,
    };
    fetch(config.saveUserSettingsUrl, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    }).catch(() => {});
  }

  // Routage de la sauvegarde via l'inspecteur commun (item / batch / défauts file).
  function savePanelSettings() { if (_inspector) _inspector.save(); else saveGlobalSettings(); }

  // Crée l'inspecteur commun (WamaInspector) câblé aux spécificités du transcriber.
  function initInspector() {
    if (!queueContainer || !window.WamaInspector) return;
    _inspector = WamaInspector.init({
      queueContainer: queueContainer,
      hideOnInspect: ['resetOptions'],
      settingsTitleSelector: '#settings-section .right-panel-section-title',
      settingsTitleInspect: '<i class="fas fa-cog me-1"></i> Paramètres de l\'élément',
      panel: { read: _panelReadValues, apply: _panelApplyValues },
      cardSettings: _cardSettings,
      renderItemActions: _renderItemActions,
      renderBatchActions: _renderBatchActions,
      saveItem: saveInspectorItem,
      saveBatch: saveInspectorBatch,
      saveGlobal: saveGlobalSettings,
      itemLabel: (id) => "l'élément #" + id,
      batchLabel: (id) => "le batch #" + id + " (tous les éléments)",
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
  // Speech recognition
  // ======================================================================
  function initSpeech() {
    if (!speakButton || !liveOutput || !liveStatus) return;
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const canRecord = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
    if (!SpeechRecognition && !canRecord) {
      speakButton.disabled = true;
      liveStatus.textContent = 'Non supporté par ce navigateur';
      return;
    }

    let listening = false;
    let finalTranscript = '';
    let mediaRecorder = null, mediaStream = null, chunks = [];

    let recognition = null;
    if (SpeechRecognition) {
      recognition = new SpeechRecognition();
      recognition.lang = 'fr-FR';
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.onerror = (event) => { liveStatus.textContent = `Erreur: ${event.error}`; };
      recognition.onresult = (event) => {
        let interim = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const tr = event.results[i][0].transcript;
          if (event.results[i].isFinal) finalTranscript += tr + '\n';
          else interim += tr;
        }
        const full = (finalTranscript + interim).trim();
        if (full && full !== '...') displayTextWithHighlight(full);
        else liveOutput.textContent = '...';
      };
    }

    function setIdle(msg) {
      listening = false;
      speakButton.classList.remove('active');
      speakButton.innerHTML = '<i class="fas fa-microphone"></i> Speak';
      if (msg) liveStatus.textContent = msg;
    }

    async function startAll() {
      finalTranscript = ''; chunks = [];
      // Révèle la zone de transcription live (masquée par défaut depuis sa fusion dans la card d'entrée)
      var liveBox = document.getElementById('transcriberLive');
      if (liveBox) { liveBox.style.display = ''; liveBox.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
      // Capture l'audio du micro (pour sauver la card). Sans micro → texte live seulement.
      if (canRecord) {
        try {
          mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
          mediaRecorder = new MediaRecorder(mediaStream);
          mediaRecorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
          mediaRecorder.onstop = uploadRealtime;
          mediaRecorder.start();
        } catch (err) { mediaRecorder = null; liveStatus.textContent = 'Micro refusé — texte live seulement'; }
      }
      listening = true;
      speakButton.classList.add('active');
      speakButton.innerHTML = '<i class="fas fa-stop"></i> Stop';
      liveStatus.textContent = 'Écoute en cours…';
      if (recognition) { try { recognition.start(); } catch (_) {} }
    }

    function stopAll() {
      if (recognition) { try { recognition.stop(); } catch (_) {} }
      if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();                 // → onstop → uploadRealtime (sauve la card)
      } else {
        setIdle(finalTranscript ? 'Session terminée' : 'En attente...');
      }
      if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }
    }

    // À l'arrêt : envoie l'audio + le texte live → crée une card « temps réel » dans la file.
    function uploadRealtime() {
      const blob = new Blob(chunks, { type: (mediaRecorder && mediaRecorder.mimeType) || 'audio/webm' });
      chunks = [];
      if (!blob.size || !config.saveRealtimeUrl) { setIdle('En attente...'); return; }
      setIdle('Enregistrement dans la file…');
      const fd = new FormData();
      const ext = (blob.type.indexOf('ogg') >= 0) ? 'ogg' : 'webm';
      fd.append('audio', blob, 'realtime.' + ext);
      fd.append('text', finalTranscript.trim());
      fd.append('language', ((recognition && recognition.lang) || 'fr').slice(0, 2));
      fetch(config.saveRealtimeUrl, { method: 'POST', headers: { 'X-CSRFToken': csrfToken }, body: fd })
        .then(r => r.json())
        .then(d => {
          if (d && d.ok) { liveStatus.textContent = 'Ajouté à la file ✓'; setTimeout(() => location.reload(), 400); }
          else { liveStatus.textContent = 'Échec de l\'enregistrement dans la file'; }
        })
        .catch(() => { liveStatus.textContent = 'Erreur réseau'; });
    }

    speakButton.addEventListener('click', () => { if (listening) stopAll(); else startAll(); });
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
      const status = (card.dataset.status || '').toUpperCase();
      bindCardActions(card);
      if (['PENDING', 'RUNNING', 'STARTED'].includes(status)) {
        startPolling(card.dataset.id);
      }
    });
    updateDownloadAllState();
  }

  // ======================================================================
  // Async backends loading (non-blocking)
  // ======================================================================
  // Descriptif dynamique du moteur (sous le menu) — composant commun WamaModelHelp.
  // Les descriptions viennent de l'endpoint backends (source : backend.description) ;
  // BACKEND_FALLBACK ne sert que pour « auto » (et de repli si l'endpoint n'en a pas).
  const BACKEND_FALLBACK = {
    auto: 'Sélectionne automatiquement le meilleur moteur disponible.',
  };
  let _modelHelp = window.WamaModelHelp ? WamaModelHelp.init({
    selectId: 'backendSelect', helpId: 'backendHelp', meta: {}, fallback: BACKEND_FALLBACK,
  }) : null;

  async function loadBackendsAsync() {
    if (!config.backendsUrl) return;
    try {
      const resp = await fetch(config.backendsUrl);
      if (!resp.ok) return;
      const data = await resp.json();
      const backends = data.backends || [];
      if (!backends.length) return;
      const meta = {};
      backends.forEach(function (b) { meta[b.name] = b; });
      if (_modelHelp) _modelHelp.setMeta(meta);   // descriptions dynamiques sous le menu

      const options = backends.map(b => {
        // Pas de suffixe « (diarisation) » : le Transcriber diarise TOUJOURS
        // (VibeVoice nativement, Whisper/Qwen via pyannote) → info technique trompeuse.
        return `<option value="${escapeHtml(b.name)}">${escapeHtml(b.display_name)}</option>`;
      }).join('');

      // Populate global panel selector and restore saved value
      const globalSel = document.getElementById('backendSelect');
      if (globalSel) {
        const savedValue = globalSel.dataset.selected || 'auto';
        globalSel.insertAdjacentHTML('beforeend', options);
        globalSel.value = savedValue;
        if (_modelHelp) _modelHelp.render();
      }

      // Populate settings modal selector (value set when modal opens)
      const settingsSel = document.getElementById('settingsBackend');
      if (settingsSel) {
        settingsSel.insertAdjacentHTML('beforeend', options);
      }
    } catch (_) {
      // silently ignore — "Auto" remains functional
    }
  }

  initUpload();
  initDragDrop();
  initYoutube();
  initExistingCards();
  initSpeech();
  initBulkActions();
  initInspector();
  loadBackendsAsync();

  // Preview compacte (double-clic) → modal de RÉSULTAT de transcription (pas l'aperçu
  // audio de l'entrée). Émis par le composant commun .wama-card-preview (media-preview.js).
  document.addEventListener('wama:card-expand', function (e) {
    if (e.detail && e.detail.id) {
      e.preventDefault();
      openResultModal(e.detail.id);
    }
  });

  // Progression globale + ETA agrégée : désormais pilotées par la brique commune
  // wama-global-progress.js (auto-démarrée). On ne double pas le poller ici.
});

// Filemanager 'Envoyer vers...' — reload page to show imported item
document.addEventListener('wama:fileimported', function(e) {
    if (e.detail && e.detail.app === 'transcriber') { window.location.reload(); }
});
