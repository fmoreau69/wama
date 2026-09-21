/**
 * WAMA Enhancer — Audio Speech Enhancement
 * Handles Resemble Enhance (quality) and DeepFilterNet 3 (speed).
 */
document.addEventListener('DOMContentLoaded', function () {
  const cfg = window.AUDIO_ENHANCER_APP || {};
  const csrfToken = cfg.csrfToken;

  const pollers = new Map();

  function csrfHeaders(extra) {
    return Object.assign({}, extra || {}, { 'X-CSRFToken': csrfToken });
  }

  function getUrl(template, id) {
    return template.replace('/0/', '/' + id + '/');
  }

  // ── Right-panel settings visibility ──────────────────────────────────────

  // getEngine + updateResembleVisibility PURGÉES (2026-08-17) : la visibilité des réglages Resemble
  // (.resemble-only) est pilotée par les CAPACITÉS du catalogue (caps.params) via la brique
  // commune WamaModelCaps (init dans index.html) — plus de test d'id de moteur en dur.

  // Denoising strength display
  const strengthSlider = document.getElementById('audioDenoisingStrength');
  const strengthVal = document.getElementById('audioStrengthValue');
  if (strengthSlider && strengthVal) {
    strengthSlider.addEventListener('input', () => {
      strengthVal.textContent = parseFloat(strengthSlider.value).toFixed(1);
    });
  }

  // ── Volet : le curseur du tirage « auto » n'est visible que sur « auto » (curseur C, 21/09) ──
  // Le volet est rendu serveur (pas de show_if de schéma dessus) : bascule d'une ligne, même
  // mécanique que le synthesizer. Les réglages Resemble (.resemble-only), eux, sont tenus par
  // WamaModelCaps (capacités du catalogue — « auto » n'en a pas, donc masqués).
  function syncAudioAutoOptions() {
    const sel = document.getElementById('audioEngine');
    const box = document.getElementById('audioAutoOptions');
    if (sel && box) box.hidden = (sel.value || 'auto') !== 'auto';
  }
  (function initAudioAutoOptions() {
    const sel = document.getElementById('audioEngine');
    if (sel) sel.addEventListener('change', syncAudioAutoOptions);
    syncAudioAutoOptions();
  })();

  // Ce que le VOLET dit — la surface de réglage vivante de cette file, appliquée à CHAQUE
  // lancement depuis le volet (▶ de card, « tout démarrer », lot). Un seul lecteur.
  function panelAudioBody() {
    return {
      engine: document.getElementById('audioEngine')?.value || 'auto',
      mode: document.getElementById('audioMode')?.value || 'both',
      denoising_strength: parseFloat(document.getElementById('audioDenoisingStrength')?.value || '0.5'),
      quality: parseInt(document.getElementById('audioQuality')?.value || '64'),
      quality_intent: document.getElementById('audioQualityIntent')?.value || '',
    };
  }

  // ── Voie d'import AUDIO : les DEUX briques communes (portage 2026-09-08) ───────────
  //
  // Fabien : « il n'y a rien de maison, c'est encore du portage ». Jusqu'ici cette voie
  // recopiait la barre de lot commune (gabarit `_audio_batch_bar.html`, 44 lignes) ET sa
  // logique (10 fonctions : détection par extension, aperçu, création, boutons), plus une
  // boucle d'upload à elle — parce que la brique batch ne savait rendre qu'UN jeu d'ids par
  // page et que la page enhancer porte deux voies (image + audio). La brique a gagné `idBase`
  // (`audioBatch…`), le gabarit commun `bid` : la voie audio n'écrit plus rien.
  //   • lot : `WamaBatchImport({ idBase:'audioBatch' })` — mêmes endpoints audio, mêmes
  //     réponses (`items/count/warnings`, `batch_id`) ; « Démarrer » poste les réglages du
  //     volet audio au lancement, comme avant ;
  //   • fichiers : `WamaImport` — `beforeFile` = le filtre d'extensions audio qu'on avait
  //     (toast sinon), lot testé sur un fichier SEUL (comportement d'avant), `afterImport` =
  //     1 → card rendue serveur (`appendAudioRow`), N → reload après consolidation.
  const _audioBatch = (typeof WamaBatchImport === 'function') ? WamaBatchImport({
    idBase:          'audioBatch',
    batchExtensions: ['txt', 'md', 'csv', 'pdf', 'docx'],
    batchPreviewUrl: cfg.audioBatchPreviewUrl,
    batchCreateUrl:  cfg.audioBatchCreateUrl,
    csrfToken:       csrfToken,
    afterCreate: async function (data, autoStart) {
      if (autoStart && data && data.batch_id && cfg.audioBatchStartUrlTemplate) {
        const startUrl = cfg.audioBatchStartUrlTemplate.replace('/0/', `/${data.batch_id}/`);
        try {
          await fetch(startUrl, {
            method: 'POST',
            headers: csrfHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(panelAudioBody()),
          });
        } catch (_e) { /* la création est faite ; le lancement se rejoue depuis la card */ }
      }
      setTimeout(() => location.reload(), 600);
    },
  }) : null;

  function initAudioImport() {
    if (typeof window.WamaImport !== 'function') {
      WamaApp.toast("Voie d'import non chargée (wama-import.js) — dépôt audio impossible", 'error');
      console.error('[Enhancer audio] WamaImport absent : wama-import.js non chargé par le gabarit');
      return;
    }
    window._importAudio = WamaImport({
      uploadUrl:        cfg.audioUploadUrl,
      consolidateUrl:   cfg.audioConsolidateUrl,
      consolidateField: 'ids',
      csrfToken:        csrfToken,
      dropZoneId:       'dropZoneAudio',
      fileInputId:      'audio-enhancer-file',
      folderInputId:    'audioEnhFolderInput',
      batch:            _audioBatch,
      beforeFile:       function (f) {
        if (/\.(mp3|wav|flac|ogg|m4a|aac|opus|wma)$/i.test(f.name)) return true;
        WamaApp.toast('Formats acceptés : MP3, WAV, FLAC, OGG, M4A, AAC, OPUS, WMA (ou fichier batch .txt/.csv/.md)');
        return false;
      },
      afterImport:      function (ids, reponses) {
        if (ids.length !== 1) { location.reload(); return; }
        appendAudioRow(reponses[0] || { id: ids[0] });
      },
    });
  }

  // ── Queue row management ──────────────────────────────────────────────────

  async function appendAudioRow(data) {
    const container = document.getElementById('audio-enhancer-queue');
    if (!container) return;

    const empty = container.querySelector('.empty-state');
    if (empty) empty.remove();

    // Card = rendu SERVEUR (plus de markup construit côté JS), REDEMANDÉE par la brique
    // commune (WamaApp.fetchCard, portage 2026-09-21 — la copie locale du fetch vivait ici).
    const card = await WamaApp.fetchCard(cfg.audioCardHtmlUrlTemplate, data.id);
    if (!card) {
      location.reload();   // repli : le rechargement rend les cards serveur
      return;
    }
    container.prepend(card);
    if (typeof initMediaPreview === 'function') initMediaPreview();
    updateAudioGlobalProgress();
  }

  async function refreshAudioCard(id) {
    // Card = partial SERVEUR unique (endpoint audio_card_html), par la brique commune ;
    // handlers délégués, le waveform des cards hors batch est inclus par le partial.
    const fresh = await WamaApp.fetchCard(cfg.audioCardHtmlUrlTemplate, id);
    const container = document.getElementById('audio-enhancer-queue');
    const existing = container ? container.querySelector(`[data-id="${id}"]`) : null;
    if (fresh && existing) {
      existing.replaceWith(fresh);
      if (typeof initMediaPreview === 'function') initMediaPreview();
    }
    return fresh;
  }

  async function updateRow(id, data) {
    const container = document.getElementById('audio-enhancer-queue');
    const card = container ? container.querySelector(`[data-id="${id}"]`) : null;
    if (!card) return;

    const status = (data.status || card.dataset.status || 'PENDING').toUpperCase();

    // ETA (moteur commun) — seed depuis l'estimateur serveur (service-based)
    if (window.WamaEta) {
      WamaEta.render(card.querySelector('.wama-eta'),
        WamaEta.update(id, { progress: data.progress || 0, status: status,
                             seedSeconds: data.estimated_seconds, modelLoaded: false }));
    }

    if (status === (card.dataset.status || '').toUpperCase()) {
      // Même état : maj légère de la progression (markup = brique _card_progress).
      if (data.progress !== undefined) {
        const fill = card.querySelector('.wama-progress-fill');
        if (fill) fill.style.width = data.progress + '%';
        const progressText = card.querySelector('.progress-text');
        if (progressText) progressText.textContent = data.progress + '%';
      }
    } else {
      // Transition d'état → re-rendu SERVEUR de la card (source unique du markup).
      await refreshAudioCard(id);
    }
  }

  // ── Per-row settings modal : le CYCLE commun (WamaParams.settingsModal, portage 21/09) ────
  // Ce qui vivait ici (coquille, pied cloné, lecture par name, recopie sur le gear, relecture
  // du volet AVANT lancement — et un `updateResembleVisibility()` qui n'existait plus) est
  // remplacé par la brique : les valeurs sont ENREGISTRÉES (audio/update, la vue les tient),
  // la card se re-rend, « Sauvegarder et lancer » lance avec les valeurs STOCKÉES de l'item.
  // Valeurs = data-* du gear lues par LE lecteur unique `WamaInspector.gearValues`.
  function openAudioSettingsModal(id, btn) {
    const schema = window.ENHANCER_AUDIO_SCHEMA || [];
    const card = (btn && btn.closest('.wama-card')) || btn;
    return WamaParams.settingsModal({
      id: id,
      title: 'Paramètres audio — #' + id,
      titleIcon: 'fa-microphone-alt',
      schema: schema,
      values: WamaInspector.gearValues(card, schema.map(function (p) { return p.name; })),
      formClass: 'audio-settings-form',
      footerTplId: 'audioSettingsFooterTpl',
      saveUrl: getUrl(cfg.audioUpdateUrlTemplate, id),
      csrf: csrfToken,
      onSaved: function (aid, restart) {
        refreshAudioCard(aid).then(function () {
          if (restart) startAudio(parseInt(aid, 10), { useStored: true });
        });
      },
    });
  }

  // ⏹ Stop : arrête le débruitage audio → item relançable (↻ via autoSync sur data-status).
  async function handleStopAudio(id) {
    if (!id) return;
    try {
      const r = await fetch(`/enhancer/audio/stop/${id}/`, { method: 'POST', headers: csrfHeaders() });
      const data = await r.json().catch(() => ({}));
      const card = document.querySelector(`#audio-enhancer-queue [data-id="${id}"]`);
      if (card && data.status) card.dataset.status = data.status;
    } catch (e) { /* non-fatal */ }
    // Re-rendu SERVEUR : sans lui la card restait visuellement « en cours » jusqu'au F5
    // (même défaut que l'avatarizer, corrigé en famille — constat Fabien 17/08).
    refreshAudioCard(id);
  }

  // Bouton de cycle commun ▶/⏹/↻ (audio) : wire délégué + auto-sync sur data-status.
  (function initAudioCycle() {
    if (!window.WamaCycleButton) return;
    const q = document.getElementById('audio-enhancer-queue');
    if (!q) return;
    WamaCycleButton.wire(q, { start: (id) => startAudio(id), stop: (id) => handleStopAudio(id) });
    WamaCycleButton.autoSync({ container: q, cardSelector: '.synthesis-card' });
  })();

  // ── Start / polling (also called from modal "Save and Start") ────────────

  async function startAudio(id, opts) {
    // ▶ depuis la card / le volet : les réglages du VOLET s'appliquent (surface vivante de
    // cette file). `useStored` (« Sauvegarder et lancer » de la modale) : corps vide, le
    // lancement lit les réglages STOCKÉS de l'item que la modale vient d'enregistrer.
    // Le format de sortie est PER-ITEM et vit désormais en base (audio/update) : plus rien à
    // relire sur le gear. La card se re-rend du serveur au passage RUNNING (updateRow).
    try {
      const body = (opts && opts.useStored) ? {} : panelAudioBody();
      const resp = await fetch(getUrl(cfg.audioStartUrlTemplate, id), {
        method: 'POST',
        headers: csrfHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (data.error) throw new Error(data.error);

      updateRow(id, { status: 'RUNNING', progress: 0 });
      pollAudioProgress(id);
    } catch (err) {
      WamaApp.toast('Erreur démarrage: ' + err.message);
    }
  }

  function pollAudioProgress(id) {
    if (pollers.has(id)) return;

    const interval = setInterval(async () => {
      try {
        const resp = await fetch(getUrl(cfg.audioProgressUrlTemplate, id));
        const data = await resp.json();
        updateRow(id, data);

        if (data.status === 'SUCCESS' || data.status === 'FAILURE') {
          clearInterval(interval);
          pollers.delete(id);
          updateAudioGlobalProgress();
        }
      } catch (e) {
        clearInterval(interval);
        pollers.delete(id);
      }
    }, 1500);

    pollers.set(id, interval);
  }

  // 🗑 RÉSIDU de suppression (cards AUDIO) — SCOPÉ à la file audio. Le `within` est indispensable
  // ici : `index.js` déclare le résidu des cards d'AMÉLIORATION, et sans scope la seconde
  // déclaration aurait écrasé la première en silence. La brique commune porte la confirmation,
  // le POST, le retrait de card, le lot vidé et le signal au gestionnaire de fichiers ; il ne
  // reste que le poller local (pas encore `WamaApp.Poller`) et deux rendus d'en-tête.
  WamaQueueActions.onDeleted(function (id) {
    if (pollers.has(id)) {
      clearInterval(pollers.get(id));
      pollers.delete(id);
    }
    const container = document.getElementById('audio-enhancer-queue');
    if (container && !container.querySelector('[data-id]')) {
      const el = document.createElement('div');
      el.className = 'empty-state text-center py-4 text-white-50';
      el.textContent = 'Aucun fichier audio en attente.';
      container.appendChild(el);
    }
    updateAudioGlobalProgress();
  }, { domain: 'audio' });

  // ── Global progress ───────────────────────────────────────────────────────

  // Barre globale AUDIO + bouton « tout télécharger » : désormais pilotés par la fonction
  // commune WamaGlobalProgress (voir l'init en fin de fichier) — zéro duplication.
  // Conservée en no-op car appelée impérativement après diverses actions ; le poll commun
  // (1,5 s) rafraîchit la barre et le bouton automatiquement.
  function updateAudioGlobalProgress() { /* no-op : cf. WamaGlobalProgress.init */ }

  // ── Button handlers ───────────────────────────────────────────────────────

  function initButtons() {
    // Start all
    const startAllBtn = document.getElementById('audio-process-btn');
    if (startAllBtn) {
      startAllBtn.addEventListener('click', async () => {
        try {
          const resp = await fetch(cfg.audioStartAllUrl, {
            method: 'POST',
            headers: csrfHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(panelAudioBody()),
          });
          const data = await resp.json();
          data.started_ids?.forEach(id => {
            updateRow(id, { status: 'RUNNING', progress: 0 });
            pollAudioProgress(id);
          });
        } catch (err) {
          WamaApp.toast('Erreur: ' + err.message);
        }
      });
    }

    // Clear all
    const clearBtn = document.getElementById('audio-clear-btn');
    if (clearBtn) {
      clearBtn.addEventListener('click', async () => {
        if (!confirm('Effacer tous les fichiers audio ?')) return;
        try {
          await fetch(cfg.audioClearUrl, { method: 'POST', headers: csrfHeaders() });
          const container = document.getElementById('audio-enhancer-queue');
          if (container) {
            container.querySelectorAll('[data-id]').forEach(card => card.remove());
            const el = document.createElement('div');
            el.className = 'empty-state text-center py-4 text-white-50';
            el.textContent = 'Aucun fichier audio en attente.';
            container.appendChild(el);
          }
          pollers.forEach(clearInterval);
          pollers.clear();
          updateAudioGlobalProgress();
        } catch (err) {
          WamaApp.toast('Erreur: ' + err.message);
        }
      });
    }

    // Download all
    const dlAllBtn = document.getElementById('audio-download-all-btn');
    if (dlAllBtn) {
      dlAllBtn.addEventListener('click', () => {
        window.location.href = cfg.audioDownloadAllUrl;
      });
    }

    // Queue table: per-row buttons (event delegation)
    const queueTable = document.getElementById('audio-enhancer-queue');
    if (queueTable) {
      queueTable.addEventListener('click', e => {
        const startBtn    = e.target.closest('.js-audio-start');
        const dlBtn       = e.target.closest('.js-audio-download');
        // ⚙ et 🗑 : plus de branche ici — délégués par la brique commune queue-actions.js,
        // ouvreur et suite déclarés plus bas, tous deux scopés à cette file (2026-08-23).

        if (startBtn) startAudio(parseInt(startBtn.dataset.id));
        if (dlBtn && !dlBtn.classList.contains('disabled')) {
          // navigation handled by <a> href
        }
      });
    }

    // ⚙ item (cards AUDIO) — ouvreur DÉCLARÉ à la brique commune (queue-actions.js), restreint
    // à la file audio. C'est ce `within` qui permet aux DEUX familles de cards de l'enhancer
    // (audio ici, amélioration dans index.js) de partager `.settings-btn` sans se marcher
    // dessus : l'ouvreur scopé est évalué avant l'ouvreur par défaut (portage 2026-08-23).
    WamaQueueActions.onSettings(function (id, btn) {
      openAudioSettingsModal(id, btn);
    }, { domain: 'audio' });

    // Resume polling for running jobs on page load
    const audioContainer = document.getElementById('audio-enhancer-queue');
    if (audioContainer) {
      audioContainer.querySelectorAll('[data-status="RUNNING"]').forEach(card => {
        pollAudioProgress(parseInt(card.dataset.id));
      });
    }

    // ── ▶ ⧉ 🗑 du LOT AUDIO : brique commune `queue-actions.js` (2026-08-27) ──────────────
    // Retrait des trois handlers locaux ET pose de `actions_communes=True domain='audio'` sur
    // l'include : un seul geste (sinon double POST). Les URLs `audio_batch_*` sont résolues par
    // la card mère via `domain_route_prefix` — plus aucun `cfg.audioBatch*UrlTemplate` recollé ici.
    //
    // DEUX spécificités déclarées, parce qu'elles ne sont PAS décoratives :
    //  • le CORPS — le volet gauche audio est la surface de réglage vivante de cette file, et
    //    elle est appliquée à CHAQUE lancement, item (`startAudio`) comme lot. Lancer avec un
    //    corps vide aurait relancé le lot avec les valeurs stockées à la création : régression
    //    muette, et incohérente avec le ▶ de la card fille juste à côté ;
    //  • la SUITE — l'audio insère et POLLE (comme la file média), il ne recharge pas.
    if (window.WamaQueueActions) {
      WamaQueueActions.onBatchStartBody(function () { return panelAudioBody(); }, { domain: 'audio' });

      WamaQueueActions.onBatchStarted(function (data) {
        (data.started || []).forEach(id => {
          updateRow(id, { status: 'RUNNING', progress: 0 });
          pollAudioProgress(id);
        });
      }, { domain: 'audio' });
    }
  }

  initAudioImport();
  initButtons();

  // Barre globale AUDIO : réutilise la fonction commune (zéro duplication), endpoint audio dédié.
  // onData : (dés)active le bouton « tout télécharger » selon le nombre de succès.
  if (window.WamaGlobalProgress && cfg.audioGlobalProgressUrl) {
    WamaGlobalProgress.init({
      url: cfg.audioGlobalProgressUrl,
      bar: 'audioGlobalProgressBar', stats: 'audioGlobalProgressStats',
      pct: 'audioGlobalProgressPct', status: 'audioGlobalStatus', eta: 'audioGlobalEta',
      onData: function (d) {
        var b = document.getElementById('audio-download-all-btn');
        if (b) b.disabled = (d.success || 0) === 0;
      },
    });
  }
});
