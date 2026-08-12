/*
 * wama-app-base.js — Plomberie JS commune aux apps WAMA (file d'attente / cards).
 *
 * Extrait du Transcriber (app de référence) pour éliminer la duplication inter-apps :
 *   - helpers sans état : escapeHtml, getUrl, csrfHeaders, csrfFetch, wordCount
 *   - WamaApp.Poller    : boucle de polling de progression résiliente (par id)
 *   - WamaApp.emptyState: insertion/retrait d'un état vide dans un conteneur de file
 *
 * Aucune dépendance. Expose un namespace global `WamaApp`.
 * Adoption : charger ce script AVANT l'index.js de l'app, puis déléguer.
 */
(function (global) {
  'use strict';

  // ── Helpers sans état ────────────────────────────────────────────────
  function escapeHtml(str) {
    return (str || '').replace(/[&<>"']/g, function (m) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m];
    });
  }

  // Remplace le segment id factice « /0/ » d'un template d'URL Django par l'id réel.
  function getUrl(template, id) {
    return (template || '').replace('/0/', '/' + id + '/');
  }

  function csrfHeaders(csrfToken, extra) {
    return Object.assign({}, extra || {}, { 'X-CSRFToken': csrfToken });
  }

  // fetch() avec en-tête CSRF injecté (les autres options sont transmises telles quelles).
  function csrfFetch(url, csrfToken, opts) {
    opts = opts || {};
    opts.headers = csrfHeaders(csrfToken, opts.headers);
    return fetch(url, opts);
  }

  function wordCount(text) {
    if (!text || !text.trim()) return 0;
    return text.trim().split(/\s+/).filter(Boolean).length;
  }

  // ── Poller : boucle de progression résiliente, indexée par id ────────
  // cfg = { urlTemplate, onData(id,data), interval=1200, maxFails=10, onGiveUp(id) }
  // Une exception dans onData ne tue PAS la boucle ; une erreur réseau transitoire
  // n'arrête le poller qu'après `maxFails` échecs consécutifs.
  function Poller(cfg) {
    cfg = cfg || {};
    this.urlTemplate = cfg.urlTemplate;
    this.onData = cfg.onData || function () {};
    this.onGiveUp = cfg.onGiveUp || function () {};
    this.interval = cfg.interval || 1200;
    this.maxFails = cfg.maxFails || 10;
    this._pollers = new Map();
  }

  Poller.prototype.has = function (id) { return this._pollers.has(id); };

  Poller.prototype.start = function (id) {
    if (this._pollers.has(id)) return;
    const self = this;
    let fails = 0;
    const handle = setInterval(function () {
      fetch(getUrl(self.urlTemplate, id))
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function (data) {
          fails = 0;
          try { self.onData(id, data); }
          catch (e) { console.error('[WamaApp.Poller] onData', id, e); }
        })
        .catch(function (err) {
          fails++;
          console.warn('[WamaApp.Poller] poll', id, 'échec', fails, err);
          if (fails >= self.maxFails) { self.stop(id); self.onGiveUp(id); }
        });
    }, this.interval);
    this._pollers.set(id, handle);
  };

  Poller.prototype.stop = function (id) {
    const handle = this._pollers.get(id);
    if (handle) { clearInterval(handle); this._pollers.delete(id); }
  };

  Poller.prototype.stopAll = function () {
    this._pollers.forEach(function (h) { clearInterval(h); });
    this._pollers.clear();
  };

  // ── État vide d'un conteneur de file ─────────────────────────────────
  // cfg = { container, cardSelector='.synthesis-card', emptyClass='empty-queue', html }
  function emptyState(cfg) {
    cfg = cfg || {};
    const container = cfg.container;
    const cardSelector = cfg.cardSelector || '.synthesis-card';
    const emptyClass = cfg.emptyClass || 'empty-queue';
    return {
      remove: function () {
        if (!container) return;
        const el = container.querySelector('.' + emptyClass);
        if (el) el.remove();
      },
      insertIfNeeded: function () {
        if (!container) return;
        const hasCards = container.querySelectorAll(cardSelector).length > 0;
        if (!hasCards && !container.querySelector('.' + emptyClass)) {
          const div = document.createElement('div');
          div.className = 'text-center py-5 ' + emptyClass;
          div.innerHTML = cfg.html || '<p class="text-white-50">Aucun élément</p>';
          container.appendChild(div);
        }
      },
    };
  }

  // ── Toast non bloquant (généralise le toast composer ; remplace les alert()) ──
  // type ∈ {success, error|danger, info, warning} — mêmes couleurs que les badges Bootstrap.
  function toast(message, type) {
    const colors = { success: '#198754', error: '#dc3545', danger: '#dc3545',
                     info: '#0dcaf0', warning: '#ffc107' };
    const el = document.createElement('div');
    el.className = 'wama-toast';
    el.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:9999;' +
      'background:' + (colors[type] || '#333') + ';color:#fff;padding:10px 16px;' +
      'border-radius:6px;font-size:.9rem;box-shadow:0 4px 12px rgba(0,0,0,.4);max-width:300px;';
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(function () { el.remove(); }, 3500);
  }

  // ── Import par URL : câble le bloc URL de la carte commune (_new_item_card.html) ──
  // Élimine le handler fetch/CSRF/spinner/erreur dupliqué dans chaque app. L'app
  // déclare la capacité dans son template (show_url=True + url_input_id/url_submit_id)
  // et fournit ici l'endpoint + un hook de succès ; TOUTE la plomberie (POST du
  // champ URL, CSRF, spinner, gestion d'erreur, reset du champ, touche Entrée) est
  // centralisée. No-op silencieux si le bloc URL n'est pas présent sur la page.
  //
  // cfg = {
  //   inputId, buttonId,        // = url_input_id / url_submit_id passés au template
  //   onSubmit(url),            // MODE DÉLÉGUÉ (préféré) : l'app traite l'URL
  //                             //   (ex. la router vers le pipeline batch commun,
  //                             //   WamaBatchImport.ingestText). Peut renvoyer une
  //                             //   Promise. Si fourni, endpoint/fieldName ignorés.
  //   endpoint,                 // MODE POST : URL d'upload de l'app (reçoit le champ)
  //   csrfToken,
  //   fieldName='media_url',    // nom du champ POST portant l'URL
  //   extraFields,              // optionnel : () => ({k:v}) champs additionnels
  //   onSuccess(data),          // MODE POST : ajout de l'item à la file (spéc. app)
  //   onEmpty,                  // optionnel : URL vide (défaut = focus input)
  //   onError(err),             // optionnel ; défaut = toast rouge
  // }
  // Retourne { submit } ou null si le bloc URL est absent.
  function initUrlImport(cfg) {
    cfg = cfg || {};
    const input = document.getElementById(cfg.inputId);
    const btn   = document.getElementById(cfg.buttonId);
    if (!input || !btn) return null;           // capacité URL non déclarée ici
    const field = cfg.fieldName || 'media_url';

    function submit() {
      const url = (input.value || '').trim();
      if (!url) {
        if (typeof cfg.onEmpty === 'function') cfg.onEmpty();
        else input.focus();
        return;
      }
      const original = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

      // Mode délégué : l'app traite l'URL elle-même (ex. la router vers le
      // pipeline batch commun via WamaBatchImport.ingestText, réutilisant le
      // formalisme batch) au lieu du POST direct d'un champ vers un endpoint.
      if (typeof cfg.onSubmit === 'function') {
        Promise.resolve()
          .then(function () { return cfg.onSubmit(url); })
          .then(function () { input.value = ''; })
          .catch(function (err) {
            if (typeof cfg.onError === 'function') cfg.onError(err);
            else toast(err.message || "Échec de l'import de l'URL", 'error');
          })
          .finally(function () { btn.disabled = false; btn.innerHTML = original; });
        return;
      }

      const fd = new FormData();
      fd.append(field, url);
      const extra = (typeof cfg.extraFields === 'function') ? (cfg.extraFields() || {}) : {};
      Object.keys(extra).forEach(function (k) { fd.append(k, extra[k]); });
      csrfFetch(cfg.endpoint, cfg.csrfToken, { method: 'POST', body: fd })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok || res.d.error) throw new Error(res.d.error || ('HTTP ' + (res.d.status || '')));
          input.value = '';
          if (typeof cfg.onSuccess === 'function') cfg.onSuccess(res.d);
        })
        .catch(function (err) {
          if (typeof cfg.onError === 'function') cfg.onError(err);
          else toast(err.message || "Échec du téléchargement de l'URL", 'error');
        })
        .finally(function () { btn.disabled = false; btn.innerHTML = original; });
    }

    btn.addEventListener('click', submit);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); submit(); }
    });
    return { submit: submit };
  }

  // ── Maps statut → apparence (source UNIQUE ; recopiées par app avant 2026-07-06) ──
  // Alignées sur le tricolore CARD_DESIGN : gris=brouillon · orange=en cours · vert=fini · rouge=échec.
  const STATUS_BADGE = {
    DRAFT: 'bg-secondary', PENDING: 'bg-secondary', RUNNING: 'bg-warning text-dark',
    SUCCESS: 'bg-success', FAILURE: 'bg-danger',
  };
  const STATUS_LABEL = {
    DRAFT: 'Brouillon', PENDING: 'En attente', RUNNING: 'En cours',
    SUCCESS: 'Terminé', FAILURE: 'Échec',
  };

  // ── Réception « Envoyer vers app » du filemanager (source UNIQUE) ────────────────
  // Le filemanager émet `wama:fileimported` avec {app, ...} après avoir créé l'item dans
  // l'app cible. Chaque app recopiait le MÊME listener de 3 lignes dans son propre JS
  // (7 copies avant 2026-07-30, 3 apps oubliées au passage). L'app courante est connue
  // globalement (`window.WAMA_CURRENT_APP`, posé par base.html depuis APP_CATALOG) :
  // le listener est donc générique et vaut pour toutes les apps, présentes et futures.
  // Une app qui sait intégrer l'item SANS recharger (le reader insère la card) pose
  // `detail.handled = true` dans son propre listener ; le repli générique s'efface alors.
  // Le report d'un tick est ce qui rend l'échappatoire possible : sans lui, ce listener —
  // enregistré en premier puisque cette brique est chargée avant le JS d'app — rechargerait
  // la page avant même que le listener de l'app ait pu s'exprimer.
  document.addEventListener('wama:fileimported', function (e) {
    const detail = e && e.detail;
    if (!detail || detail.app !== global.WAMA_CURRENT_APP) return;
    setTimeout(function () { if (!detail.handled) global.location.reload(); }, 0);
  });

  // ── Lecture exclusive globale (source UNIQUE ; fix transcriber edit.js porté 2026-08-04) ──
  // Démarrer un média met en pause tous les autres <audio>/<video> de la page (cards
  // avatarizer, aperçus du volet droit…). 'play' ne bulle pas → phase de capture.
  // Les players WamaAudioPlayer (Audio() HORS DOM : leurs événements n'atteignent jamais
  // ce listener) gèrent leur exclusivité interne et appellent pauseDomMedia() en retour —
  // les deux mondes se coupent mutuellement.
  // Échappatoire : data-wama-multiplay sur le média ou un ancêtre (lecture simultanée voulue).
  function pauseDomMedia(except) {
    document.querySelectorAll('audio, video').forEach(function (m) {
      if (m === except || m.paused) return;
      if (m.closest && m.closest('[data-wama-multiplay]')) return;
      try { m.pause(); } catch (_) {}
    });
  }
  // ── Exclusivité INTER-ONGLETS (BroadcastChannel) ───────────────────────────
  // L'exclusivité ci-dessus est locale à UNE page. Deux onglets WAMA s'ignorent :
  // vocaliser depuis l'AI-Assistant (accueil) puis lancer un aperçu dans un autre
  // onglet superposait les deux sons. On diffuse donc « je prends la parole » ;
  // les autres onglets se taisent. Aucun état partagé, aucun verrou : un message,
  // et seul l'émetteur continue. Pas de boucle possible — on n'émet que sur `play`,
  // et faire taire n'émet rien.
  // data-wama-multiplay garde sa sémantique : ces médias ne RÉCLAMENT pas le canal
  // (le cam_analyzer joue 4 caméras de front, il n'a pas à faire taire les autres).
  var mediaChannel = null;
  try {
    if (typeof BroadcastChannel !== 'undefined') mediaChannel = new BroadcastChannel('wama-media');
  } catch (_) { mediaChannel = null; }   // navigateur ancien / contexte restreint → dégradation locale
  var TAB_ID = Math.random().toString(36).slice(2) + Date.now().toString(36);

  function claimAudioChannel() {
    if (!mediaChannel) return;
    try { mediaChannel.postMessage({ t: 'play', tab: TAB_ID }); } catch (_) {}
  }
  function silenceLocal() {
    pauseDomMedia(null);
    if (global.WamaAudioPlayer) WamaAudioPlayer.pauseAll();
    stopSpeech();
  }
  if (mediaChannel) {
    mediaChannel.onmessage = function (e) {
      var d = e && e.data;
      if (!d || d.t !== 'play' || d.tab === TAB_ID) return;
      silenceLocal();
    };
  }

  document.addEventListener('play', function (e) {
    const playing = e.target;
    if (playing.closest && playing.closest('[data-wama-multiplay]')) return;
    pauseDomMedia(playing);
    if (global.WamaAudioPlayer) WamaAudioPlayer.pauseAll();
    stopSpeech();   // la voix de synthèse est un média comme un autre : elle se fait couper
    claimAudioChannel();
  }, true);

  // ── Vocalisation (TTS) : canal de parole UNIQUE pour toute la plateforme ────
  // L'exclusivité ci-dessus ne suffit pas pour la parole, et ce n'est PAS un
  // problème de lecture mais de REQUÊTE. Entre le clic sur 🔊 et l'arrivée de
  // l'audio il s'écoule un temps NON BORNÉ (au 1er appel, le modèle se charge).
  // N clics = N requêtes en vol dont les réponses reviennent ensemble : couper la
  // lecture au début de la fonction ne sert à rien, il n'y a encore rien à couper.
  // D'où un jeton de génération : une réponse issue d'une génération périmée est
  // JETÉE sans être jouée, et la requête en vol est abandonnée.
  // Constaté sur l'AI-Assistant (clics répétés pendant le chargement de Kokoro).
  let speechGen = 0;         // génération courante
  let speechAudio = null;    // lecture en cours (Audio() hors DOM)
  let speechAbort = null;    // requête en vol
  let speechUrl = null;      // ObjectURL à révoquer

  function stopSpeechPlayback() {
    if (speechAudio) { try { speechAudio.pause(); } catch (_) {} speechAudio = null; }
    if (speechUrl) { try { URL.revokeObjectURL(speechUrl); } catch (_) {} speechUrl = null; }
  }
  function stopSpeech() {
    stopSpeechPlayback();
    if (speechAbort) { try { speechAbort.abort(); } catch (_) {} speechAbort = null; }
  }

  const Speech = {
    /** Réserve le canal de parole et renvoie un jeton de tour.
     *  Coupe la vocalisation en cours ET invalide toute requête antérieure.
     *    const turn = WamaApp.Speech.claim();
     *    const r = await fetch(url, { signal: turn.signal, ... });
     *    turn.play(blob);            // ne joue QUE si ce tour est encore le dernier
     *  `turn.valid()` se teste après CHAQUE await si du travail s'intercale. */
    claim: function () {
      stopSpeech();
      const gen = ++speechGen;
      speechAbort = (typeof AbortController !== 'undefined') ? new AbortController() : null;
      return {
        signal: speechAbort ? speechAbort.signal : undefined,
        valid: function () { return gen === speechGen; },
        play: function (src) { return gen === speechGen ? Speech.play(src) : null; },
      };
    },

    /** Joue un Blob (ou une URL) sur le canal de parole, en coupant le reste de
     *  la page. Renvoie l'Audio, ou null si la source est vide. */
    play: function (src) {
      if (!src) return null;
      stopSpeechPlayback();
      let url = src;
      if (typeof Blob !== 'undefined' && src instanceof Blob) {
        url = URL.createObjectURL(src);
        speechUrl = url;
      }
      pauseDomMedia(null);
      if (global.WamaAudioPlayer) WamaAudioPlayer.pauseAll();
      claimAudioChannel();          // la voix fait taire les AUTRES onglets aussi
      const a = new Audio(url);
      speechAudio = a;
      const done = function () { if (speechAudio === a) stopSpeechPlayback(); };
      a.addEventListener('ended', done);
      a.addEventListener('error', done);
      const p = a.play();
      if (p && p.catch) p.catch(function () {});   // autoplay refusé → pas d'exception non capturée
      return a;
    },

    stop: stopSpeech,
    isSpeaking: function () { return !!(speechAudio && !speechAudio.paused); },
  };

  // ── Onglet ciblé par l'ancre (#about-pane, #help-pane…) ─────────────────────
  // Les routes /about/ et /help/ des apps REDIRIGENT vers l'index ancré sur l'onglet
  // (brique AppAboutView/AppHelpView, common/views.py) : au chargement, on active
  // l'onglet Bootstrap dont le pane porte l'id de l'ancre. Générique — vaut pour tout
  // pane du gabarit, extra_tab_panes compris.
  document.addEventListener('DOMContentLoaded', function () {
    const id = (location.hash || '').slice(1);
    if (!id) return;
    const pane = document.getElementById(id);
    if (!pane || !pane.classList.contains('tab-pane')) return;
    const btn = document.querySelector('button[data-bs-target="#' + id + '"]');
    if (btn && global.bootstrap && bootstrap.Tab) bootstrap.Tab.getOrCreateInstance(btn).show();
  });

  global.WamaApp = {
    escapeHtml: escapeHtml,
    getUrl: getUrl,
    csrfHeaders: csrfHeaders,
    csrfFetch: csrfFetch,
    wordCount: wordCount,
    Poller: Poller,
    emptyState: emptyState,
    toast: toast,
    initUrlImport: initUrlImport,
    pauseDomMedia: pauseDomMedia,
    claimAudioChannel: claimAudioChannel,
    Speech: Speech,
    STATUS_BADGE: STATUS_BADGE,
    STATUS_LABEL: STATUS_LABEL,
  };
})(window);
