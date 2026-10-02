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

  // Lit une réponse JSON en DISANT ce qui s'est passé quand ce n'en est pas.
  //
  // ⚠⚠ MESURÉ le 2026-09-23. Les deux surfaces de l'assistant faisaient `await r.json()` sans
  // regarder `r.ok`. Un tour trop long (le modèle de niveau dev, 23 Go, chargé sur un budget
  // de 3,6 Go → offload CPU) dépasse le `timeout = 120` de gunicorn, qui rend une PAGE HTML
  // 504. L'utilisateur lisait alors « Network error: Unexpected token '<', "<html><hea"… » :
  // le message parle du parseur JSON, jamais de ce qui a échoué.
  // Un serveur qui rend du HTML à un appel JSON a TOUJOURS une raison ; la dire est le
  // minimum, et 504 en a une que l'utilisateur peut comprendre et corriger.
  function jsonOrExplain(response) {
    if (response.ok) return response.json();
    var messages = {
      504: 'Le serveur a mis trop de temps à répondre (plus de 2 minutes). '
         + 'Un modèle trop gros pour la mémoire libre peut mettre plusieurs minutes : '
         + 'réessayez, ou choisissez un modèle plus léger.',
      502: 'Le serveur a coupé la connexion (502). Le traitement a peut-être été interrompu.',
      403: 'Accès refusé (403) — session expirée ? Rechargez la page.',
      500: 'Erreur interne du serveur (500). Elle est journalisée côté serveur.',
    };
    return Promise.reject(new Error(messages[response.status]
                                    || ('Le serveur a répondu ' + response.status + '.')));
  }

  // Jeton CSRF de la page : le champ caché d'un formulaire, sinon le cookie. (Le même geste
  // vivait en ligne dans base.html ; il est exposé ici pour les briques communes.)
  function csrfToken() {
    var el = document.querySelector('[name=csrfmiddlewaretoken]');
    if (el && el.value) return el.value;
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  // ── « Libérer la carte et lancer » (B1, 2026-09-20) ───────────────────────────────────────
  // Un item EN ATTENTE DE RESSOURCES porte ce lien (`common/_card_state.html`, quand l'app lui
  // donne `app` et `pk`). C'est l'ACCORD EXPLICITE de l'utilisateur : le gouverneur ne décharge
  // jamais d'office. Délégué au document : aucune ligne par app, les cards rendues plus tard
  // sont couvertes. L'accord est consommé par la re-livraison suivante de l'item (≤ 45 s).
  document.addEventListener('click', function (e) {
    var a = e.target && e.target.closest ? e.target.closest('.vram-grant[data-vram-grant-url]') : null;
    if (!a) return;
    e.preventDefault();
    var ok = global.confirm('Libérer toute la carte graphique pour lancer cet élément ?\n' +
      'Les modèles résidents (voix de l\'assistant comprise) seront déchargés le temps du ' +
      'traitement, puis rechargés.');
    if (!ok) return;
    csrfFetch(a.dataset.vramGrantUrl, csrfToken(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app: a.dataset.app, item: a.dataset.item }),
    })
      .then(function (r) { return r.json().then(function (d) { return [r.ok, d]; }); })
      .then(function (res) {
        var d = res[1] || {};
        toast(d.message || (res[0] ? 'Accord enregistré' : 'Accord non enregistré'),
              res[0] && d.success ? 'success' : 'error');
      })
      .catch(function () { toast('Accord non enregistré', 'error'); });
  });

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
  // ⚠ La DURÉE dépend du type depuis le 2026-09-27 (constat de Fabien : « le temps d'affichage
  // de la pop-up d'erreur est un peu court, je manque de temps pour copier le texte »). Une
  // confirmation se lit d'un coup d'œil ; un message d'ERREUR se lit, se comprend, et se
  // RECOPIE — souvent dans un rapport. Les 3,5 s uniformes traitaient les deux pareil.
  // Trois réponses, et non une seule : plus de temps, le survol qui SUSPEND la disparition
  // (on ne court pas après un texte qu'on est en train de sélectionner), et une croix.
  const TOAST_MS = { error: 15000, danger: 15000, warning: 10000 };
  const TOAST_DEFAULT_MS = 3500;

  function toast(message, type) {
    const colors = { success: '#198754', error: '#dc3545', danger: '#dc3545',
                     info: '#0dcaf0', warning: '#ffc107' };
    const lasting = TOAST_MS[type] || TOAST_DEFAULT_MS;
    const el = document.createElement('div');
    el.className = 'wama-toast';
    el.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:9999;' +
      'background:' + (colors[type] || '#333') + ';color:#fff;padding:10px 16px;' +
      'border-radius:6px;font-size:.9rem;box-shadow:0 4px 12px rgba(0,0,0,.4);max-width:420px;' +
      // `user-select` explicite : le texte d'une erreur est fait pour être COPIÉ.
      'user-select:text;white-space:pre-wrap;word-break:break-word;';
    el.textContent = message;

    let timer = null;
    const close = function () { if (timer) clearTimeout(timer); el.remove(); };
    const arm = function () { timer = setTimeout(close, lasting); };

    // Messages qui DURENT : on peut les fermer soi-même, et le survol suspend leur retrait.
    // ⚠ AUCUN nœud ajouté dans l'élément — pas de croix « × » : `textContent` d'un toast est
    // LU par les sondes du smoke (`ui_smoke.py:1319` collecte les textes, `:2233` compare la
    // réponse visible d'une action de pied de modale). Une croix insérée comme premier enfant
    // aurait fait lire « ×Erreur… » — une régression invisible en développement, et fausse
    // seulement là où quelqu'un compare. L'affordance passe donc par le `title` et le curseur.
    if (TOAST_MS[type]) {
      el.setAttribute('title', 'Cliquer pour fermer');
      el.style.cssText += 'cursor:pointer;';
      el.addEventListener('click', function () {
        // Un clic qui termine une SÉLECTION ne ferme pas : on est justement en train de
        // copier le message. C'est le geste que ce toast est fait pour permettre.
        const selected = window.getSelection ? String(window.getSelection()) : '';
        if (selected) return;
        close();
      });
      // Survol = lecture en cours : on ne retire pas sous les yeux de qui lit.
      el.addEventListener('mouseenter', function () { if (timer) clearTimeout(timer); });
      el.addEventListener('mouseleave', arm);
    }
    document.body.appendChild(el);
    arm();
    return el;
  }

  // ── Confirmation COMMUNE, avec une OPTION à cocher (2026-10-01) ────────────────────
  // `window.confirm` ne sait porter qu'une question : il ne peut pas demander, dans le même geste,
  // « supprimer aussi le fichier ? » (décision de Fabien : case DÉCOCHÉE par défaut). Cette
  // modale le fait, et rend une promesse `{ok, option}`.
  //   opts = { text, okLabel='Confirmer', danger=true,
  //            option: {label, checked=false} | null,   // case proposée (absente si null)
  //            details: ['nom', …],                      // ce que l'option concerne (5 montrés)
  //            input: {label, placeholder, value} | null } // champ texte (« Transférer à… »)
  // Rend `{ok, option, value}` — `value` : le texte saisi (champ `input`), '' sinon.
  // Repli sur `window.confirm` si Bootstrap manque : la question reste posée, l'option tombe.
  // ⚠ Le harnais nocturne y répond par `ui_smoke.accept_dialogs` (comme il accepte un
  // `confirm` natif) : ne pas renommer `.wama-confirm` / `[data-confirm-ok]` / `[data-confirm-option]`
  // sans lui.
  function ask(opts) {
    opts = opts || {};
    if (!global.bootstrap || !global.bootstrap.Modal) {
      if (opts.input) {
        const typed = global.prompt(opts.text || '', opts.input.value || '');
        return Promise.resolve({ ok: typed !== null, option: false, value: (typed || '').trim() });
      }
      return Promise.resolve({ ok: global.confirm(opts.text || ''), option: false, value: '' });
    }
    return new Promise(function (resolve) {
      const modal = document.createElement('div');
      modal.className = 'modal fade wama-confirm';
      modal.tabIndex = -1;
      const optionId = 'wama-confirm-opt-' + Date.now();
      const inputId = 'wama-confirm-input-' + Date.now();
      const input = opts.input ? (
        '<div class="mt-3"><label class="form-label small" for="' + inputId + '">' +
          escapeHtml(opts.input.label || '') + '</label>' +
          '<input type="text" class="form-control form-control-sm bg-dark text-light border-secondary" id="' +
          inputId + '" data-confirm-input autocomplete="off" placeholder="' +
          escapeHtml(opts.input.placeholder || '') + '" value="' + escapeHtml(opts.input.value || '') + '">' +
        '</div>') : '';
      const names = (opts.details || []).slice(0, 5).map(function (n) {
        return '<li class="text-truncate">' + escapeHtml(n) + '</li>';
      }).join('');
      const more = (opts.details || []).length > 5
        ? '<li>… et ' + ((opts.details || []).length - 5) + ' autre(s)</li>' : '';
      const option = opts.option ? (
        '<div class="form-check mt-3">' +
          '<input class="form-check-input" type="checkbox" id="' + optionId + '" data-confirm-option' +
          (opts.option.checked ? ' checked' : '') + '>' +
          '<label class="form-check-label" for="' + optionId + '">' + escapeHtml(opts.option.label) + '</label>' +
          (names ? '<ul class="small mb-0 mt-1 ps-4 text-light">' + names + more + '</ul>' : '') +
        '</div>') : '';
      modal.innerHTML =
        '<div class="modal-dialog modal-dialog-centered"><div class="modal-content bg-dark text-light border-secondary">' +
          '<div class="modal-body"><div style="white-space:pre-wrap">' + escapeHtml(opts.text || '') + '</div>' +
            input + option + '</div>' +
          '<div class="modal-footer border-secondary py-2">' +
            '<button type="button" class="btn btn-sm btn-outline-light" data-confirm-cancel>Annuler</button>' +
            '<button type="button" class="btn btn-sm ' + (opts.danger === false ? 'btn-primary' : 'btn-danger') +
              '" data-confirm-ok>' + escapeHtml(opts.okLabel || 'Confirmer') + '</button>' +
          '</div></div></div>';
      document.body.appendChild(modal);
      let answer = { ok: false, option: false, value: '' };
      const bs = global.bootstrap.Modal.getOrCreateInstance(modal);
      const field = modal.querySelector('[data-confirm-input]');
      modal.querySelector('[data-confirm-ok]').addEventListener('click', function () {
        const box = modal.querySelector('[data-confirm-option]');
        answer = { ok: true, option: !!(box && box.checked), value: field ? field.value.trim() : '' };
        bs.hide();
      });
      if (field) {
        field.addEventListener('keydown', function (ev) {
          if (ev.key === 'Enter') { ev.preventDefault(); modal.querySelector('[data-confirm-ok]').click(); }
        });
      }
      modal.querySelector('[data-confirm-cancel]').addEventListener('click', function () { bs.hide(); });
      modal.addEventListener('shown.bs.modal', function () {
        (field || modal.querySelector('[data-confirm-ok]')).focus();
      });
      modal.addEventListener('hidden.bs.modal', function () {
        bs.dispose();
        modal.remove();
        resolve(answer);
      });
      bs.show();
    });
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
    AWAITING_RESOURCES: 'bg-awaiting',
    SUCCESS: 'bg-success', FAILURE: 'bg-danger',
    STALE: 'bg-stale',
  };
  const STATUS_LABEL = {
    DRAFT: 'Brouillon', PENDING: 'En attente', RUNNING: 'En cours',
    AWAITING_RESOURCES: 'En attente de ressources',
    SUCCESS: 'Terminé', FAILURE: 'Échec',
    STALE: 'Périmé',
  };

  // ── Les états VIENNENT DU SERVEUR (2026-09-18) ─────────────────────────────────────────────
  // `window.WAMA_STATES` est poussé par `base.html` depuis `common/utils/state_presentation.py`
  // — la MÊME source que les gabarits et que le vocabulaire Python. Les deux maps ci-dessus
  // restent en REPLI : une page qui ne recevrait pas la charge continue d'afficher juste, au
  // lieu de n'afficher rien. (Elles ne portent PAS les alias : c'est voulu, le repli est un
  // filet, pas une seconde source.)
  function _states() { return global.WAMA_STATES || null; }

  // Jumeau client de `normalize_job_status` : traduit un état QUELCONQUE (minuscules du monde
  // Lab, vocabulaire Celery…) vers le vocabulaire commun. Sans lui, le navigateur ne sait pas
  // lire un `completed`, et chaque app réécrivait sa table — 5 copies mesurées.
  function normalizeStatus(value) {
    var s = String(value == null ? '' : value).toUpperCase();
    var srv = _states();
    return ((srv && srv.aliases) || {})[s] || s;
  }

  function statusLabel(value) {
    var s = normalizeStatus(value), srv = _states();
    return ((srv && srv.labels) || STATUS_LABEL)[s] || s;
  }

  function statusBadge(value) {
    var s = normalizeStatus(value), srv = _states();
    return ((srv && srv.badges) || STATUS_BADGE)[s] || 'bg-secondary';
  }

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

  // ── Fichiers SERVEUR → File(s) du formulaire ──────────────────────────────────
  // Le geste commun de MediaPicker, du drag depuis l'explorateur et de tout canal à venir :
  // matérialiser un chemin serveur (temp utilisateur, MONTAGE) en `File`, puis le poser dans
  // l'`<input type=file>` de la card et déclencher son `change` — c'est l'app qui fait le
  // reste, par le handler qu'elle a déjà.
  //
  // GLOBAL PAR NÉCESSITÉ (2026-09-05, MEDIA_STORAGE_TIERING §8.6 D5) : l'explorateur est un
  // volet de base.html présent sur TOUTES les pages, donc son consommateur doit l'être aussi.
  // Une 1ʳᵉ version vivait dans wama-import.js — que seules les apps GÉNÉRÉES chargent
  // (`_app_scripts.html`, mesuré : 0 des 10 apps en place) — donc introuvable là où le drag
  // a lieu. Avant cette brique : un 3ᵉ canal d'événement (`filemanager:filedrop`) que chaque
  // app devait écouter, imager ne l'écoutait pas (drag muet), avatarizer re-téléchargeait
  // depuis /media/ (donc jamais un fichier de montage, servi ailleurs).
  function filesFromServerPaths(entries) {
    const mediaUrl = global.MEDIA_URL || '/media/';
    function urlOf(path) {
      const m = /^mounts\/(\d+)\/(.*)$/.exec(path || '');
      if (m) return '/filemanager/api/mounts/' + m[1] + '/serve/' + encodeURI(m[2]);
      return mediaUrl + encodeURI(path || '');
    }
    return Promise.all((entries || []).map(function (e) {
      return fetch(urlOf(e.path)).then(function (resp) {
        if (!resp.ok) throw new Error('HTTP ' + resp.status + ' — ' + (e.name || e.path));
        return resp.blob();
      }).then(function (blob) {
        const name = e.name || String(e.path || '').split('/').pop() || 'fichier';
        return new File([blob], name, { type: blob.type || e.mime || '' });
      }).catch(function (err) {
        toast('Lecture impossible : ' + err.message, 'error');
        return null;
      });
    })).then(function (files) { return files.filter(Boolean); });
  }

  /** Pose des File dans un input et déclenche son `change`. Un input sans `multiple` ne
   *  reçoit que le premier. Rend false si le navigateur n'a pas DataTransfer. */
  function injectFiles(input, files) {
    if (!input || !files || !files.length) return false;
    try {
      const dt = new DataTransfer();
      (input.multiple ? files : files.slice(0, 1)).forEach(function (f) { dt.items.add(f); });
      input.files = dt.files;
    } catch (e) {
      return false;
    }
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  }

  // ── DÉSIGNATIONS : un fichier déjà dans WAMA, POINTÉ au lieu d'être re-téléversé ──────
  // (2026-09-28, `media_paths.received_inputs`). Un `<input type=file>` ne peut pas porter un
  // chemin : la désignation vit sur l'input (`data-designated-path`), et le formulaire de
  // création la poste sous `<champ>__designated` par `appendInput`. Un fichier choisi ensuite
  // dans l'input la remplace (le `change` natif efface la désignation, cf. plus bas).
  const DESIGNATION_SUFFIX = '__designated';

  /** Pose une désignation (`{designation, name}`) dans un input de port, puis son `change`. */
  function designateInto(input, item) {
    if (!input || !item || !item.designation) return false;
    try { input.value = ''; } catch (e) { /* input en lecture seule : sans effet */ }
    input.dataset.designatedPath = item.designation;
    input.dataset.designatedName = item.name || item.designation.split('/').pop();
    input.dispatchEvent(new CustomEvent('change', { bubbles: true, detail: { designated: true } }));
    return true;
  }

  /** La désignation d'un input, ou null. */
  function designationOf(input) {
    return (input && input.dataset && input.dataset.designatedPath)
      ? { path: input.dataset.designatedPath, name: input.dataset.designatedName || '' } : null;
  }

  function clearDesignation(input) {
    if (!input || !input.dataset) return;
    delete input.dataset.designatedPath;
    delete input.dataset.designatedName;
  }

  /** Ajoute au FormData un fichier OU un pseudo-fichier désigné (`{designation}`, celui que
   *  `WamaImport` remet à `afterAttach`), sous `field`. Pour une app qui GARDE l'objet reçu
   *  plutôt que de relire l'input (avatarizer). Rend true si quelque chose a été posé. */
  function appendFile(fd, field, f) {
    if (!f) return false;
    if (typeof f.designation === 'string' && f.designation) {
      fd.append(field + DESIGNATION_SUFFIX, f.designation);
    } else {
      fd.append(field, f);
    }
    return true;
  }

  /** Ajoute au FormData le fichier de l'input OU sa désignation, sous `field`. Rend true si
   *  quelque chose a été posé. Le geste des formulaires de création des apps « attache ». */
  function appendInput(fd, input, field) {
    const d = designationOf(input);
    if (d) return appendFile(fd, field, { designation: d.path });
    return appendFile(fd, field, input && input.files && input.files[0]);
  }

  // Un fichier CHOISI dans l'input (sélecteur, dépôt) remplace une désignation antérieure : un
  // `change` natif (sans `detail.designated`) l'efface. Phase de capture : avant les écouteurs
  // de l'app, qui lisent donc l'état juste.
  document.addEventListener('change', function (e) {
    const t = e.target;
    if (t && t.type === 'file' && !(e.detail && e.detail.designated) && t.files && t.files.length) {
      clearDesignation(t);
    }
  }, true);

  /** La tuile MÉDIATHÈQUE d'une card : l'asset choisi est DÉSIGNÉ par la voie d'import de la
   *  card (`WamaImport`, qui connaît son mode crée/attache) — aucun téléchargement. Repli, pour
   *  une page sans cette voie : l'ancien geste (fichier matérialisé puis injecté). */
  function pickFromLibrary(opts) {
    opts = opts || {};
    if (typeof global.MediaPicker === 'undefined') {
      toast('Médiathèque indisponible sur cette page (media-picker.js non chargé).', 'error');
      return;
    }
    const input = document.getElementById(opts.fileInputId);
    // `onPick` = une DÉSIGNATION : la fenêtre montre les trois provenances (miens, partagés,
    // système) ; `prefer` = l'onglet d'ouverture (ex. `avatar` dans la catégorie `image`).
    global.MediaPicker.open({
      type: opts.type || 'all',
      prefer: opts.prefer,
      onPick: function (asset) {
        const imp = global.WamaImport && global.WamaImport.forElement
          && global.WamaImport.forElement(opts.fileInputId);
        const item = { path: asset.path, name: (asset.path || '').split('/').pop(),
                       type: asset.mime_type || '' };
        if (imp && imp.handleDesignations && asset.path) { imp.handleDesignations([item]); return; }
        // Un port qu'aucune voie d'import ne porte (port SECONDAIRE de la card v4, référence)
        // le DÉCLARE (`designate`) : l'asset y est pointé, et le formulaire de l'app le poste
        // par `appendInput` (2026-09-29). Sans cette déclaration, l'ancien geste ci-dessous.
        if (opts.designate && input && asset.path) {
          designateInto(input, { designation: asset.path, name: item.name });
          return;
        }
        filesFromServerPaths([{ path: asset.path, name: item.name, mime: item.type }])
          .then(function (files) { if (files.length) injectFiles(input, files); });
      },
    });
  }

  /** AJOUT À LA FILE depuis la card d'entrée — le geste du mode ATTACHE (`depot_cree=False`).
   *
   *  POURQUOI une brique (2026-10-01, demande de Fabien) : imager, avatarizer, composer et
   *  synthesizer écrivaient chacun le même formulaire — consigne, réglages, fichier joint par
   *  port (ou désigné depuis la médiathèque), POST, bouton « Envoi… », toast, card affichée —
   *  et le générateur d'apps en écrivait une 5ᵉ version (Writer). Une seule ici.
   *  Règle des deux temps (CARD_DESIGN §11.11) : on AJOUTE, rien n'est lancé ; ▶ lance.
   *
   *  opts = {
   *    url:          vue d'ajout de l'app (POST, réponse JSON `{id}` ou `{error}`) ;
   *    button:       le bouton (élément ou id) — la brique s'y abonne ;
   *    csrfToken:    facultatif (repli : `csrfToken()` de la page) ;
   *    prompt:       {inputId, field} — la consigne de la card, postée sous `field` ;
   *    paramsHostId: hôte `WamaParams` dont les valeurs sont postées (les réglages du volet) ;
   *                  la consigne de la card PRIME sur un champ homonyme du volet ;
   *    ports:        [{inputId, field, urlField, urlInputId}] — fichier joint OU désigné
   *                  (`appendInput`) ; sans fichier, l'URL du port est postée sous `urlField`.
   *                  Le champ URL est `urlInputId`, sinon le `[data-port-url]` de l'onglet du
   *                  port. Un port SANS `urlField` dont l'URL est remplie est REFUSÉ, avec le
   *                  motif : une URL ignorée en silence est le pire des cas ;
   *    extraFields:  function (fd) — les champs propres à l'app ;
   *    validate:     function (fd) → message d'erreur, ou '' (rien n'est posté) ;
   *    successMessage: texte, ou function (data) → texte, du toast de succès ;
   *    onAdded:      function (data) — défaut : recharger la page ;
   *    onSettled:    function () — après l'envoi, réussi ou non, bouton rendu (l'app y
   *                  recalcule l'état de son bouton : appariement, entrées requises) ;
   *    reset:        vider la consigne et les ports après l'ajout (défaut true).
   *  }
   *  La consigne postée est l'ORIGINALE quand `WamaPromptEnrich` l'a enrichie à l'écran
   *  (invariant `WAMA_LLM` : l'enrichi se recalcule à l'ingestion, jamais figé à la création).
   *  Rend la fonction de soumission (appel programmatique, tests). */
  function addToQueue(opts) {
    opts = opts || {};
    const button = typeof opts.button === 'string' ? document.getElementById(opts.button)
                                                   : opts.button;
    const urlOf = function (port) {
      if (port.urlInputId) return document.getElementById(port.urlInputId);
      const pane = port.inputId && document.querySelector('[data-port-input="' + port.inputId + '"]');
      const el = pane && pane.querySelector('[data-port-url]');
      return el ? el : null;
    };
    const promptValue = function (el) {
      const enrich = global.WamaPromptEnrich && global.WamaPromptEnrich.get
        && global.WamaPromptEnrich.get(el);
      if (enrich && enrich.snapshot && enrich.snapshot().state === 'processed') {
        return (enrich.original || '').trim();
      }
      return (el.value || '').trim();
    };

    function build() {
      const fd = new FormData();
      const host = opts.paramsHostId && document.getElementById(opts.paramsHostId);
      if (host && global.WamaParams && global.WamaParams.read) {
        const v = global.WamaParams.read(host);
        Object.keys(v).forEach(function (k) {
          if (v[k] !== '' && v[k] != null) fd.append(k, v[k]);
        });
      }
      const p = opts.prompt;
      const promptEl = p && document.getElementById(p.inputId);
      if (promptEl) fd.set(p.field || 'prompt', promptValue(promptEl));
      let refusal = '';
      (opts.ports || []).forEach(function (port) {
        const input = document.getElementById(port.inputId);
        if (appendInput(fd, input, port.field || 'file')) return;
        const url = urlOf(port);
        const value = url && url.value.trim();
        if (!value) return;
        if (port.urlField) fd.append(port.urlField, value);
        else refusal = refusal || ("Cette app ne télécharge pas encore depuis une URL : importez le "
                                   + "fichier ou prenez-le dans la médiathèque.");
      });
      if (typeof opts.extraFields === 'function') opts.extraFields(fd);
      return { fd: fd, refusal: refusal || (typeof opts.validate === 'function' ? opts.validate(fd) : '') };
    }

    function clear() {
      const promptEl = opts.prompt && document.getElementById(opts.prompt.inputId);
      if (promptEl) promptEl.value = '';
      (opts.ports || []).forEach(function (port) {
        const input = document.getElementById(port.inputId);
        if (input) { try { input.value = ''; } catch (e) { /* lecture seule */ } clearDesignation(input); }
        const url = urlOf(port);
        if (url) url.value = '';
      });
    }

    function submit() {
      const built = build();
      if (built.refusal) { toast(built.refusal, 'error'); return Promise.resolve(null); }
      const idle = button ? button.innerHTML : '';
      if (button) {
        button.disabled = true;
        button.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i> Envoi…';
      }
      return csrfFetch(opts.url, opts.csrfToken || csrfToken(), { method: 'POST', body: built.fd })
        // Un refus porte son motif en JSON (`{error}`, quel que soit le statut — 400, 403, 409…) :
        // le lire, pas le remplacer. Sans motif lisible (page HTML d'un 502/504), l'explication
        // commune de `jsonOrExplain`.
        .then(function (r) {
          if (r.ok) return r.json();
          return r.json()
            .then(function (j) { if (j && j.error) return j; throw new Error('sans motif'); })
            .catch(function () { return jsonOrExplain(r); });
        })
        .then(function (data) {
          if (!data || data.error) {
            toast((data && data.error) || 'Ajout refusé.', 'error');
            return null;
          }
          const msg = typeof opts.successMessage === 'function' ? opts.successMessage(data)
                                                                : opts.successMessage;
          toast(msg || 'Ajouté à la file — réglez-le si besoin, puis ▶ pour lancer.', 'success');
          if (global.WamaFM && global.WamaFM.uploaded) global.WamaFM.uploaded();
          if (opts.reset !== false) clear();
          if (typeof opts.onAdded === 'function') opts.onAdded(data);
          else global.location.reload();
          return data;
        })
        .catch(function (err) { toast(String(err && err.message || err), 'error'); return null; })
        .then(function (data) {
          if (button) { button.disabled = false; button.innerHTML = idle; }
          if (typeof opts.onSettled === 'function') opts.onSettled(data);
          return data;
        });
    }

    if (button && !button._wamaAddToQueue) {
      button._wamaAddToQueue = true;
      button.addEventListener('click', function (e) { e.preventDefault(); submit(); });
    }
    return submit;
  }

  /** Card rendue par le SERVEUR (vue `card_html` de l'app), prête à insérer — ou null.
   *
   *  Source unique du markup (CARD_DESIGN §3) : le JS ne reconstruit jamais une card, il la
   *  redemande. `urlTemplate` porte l'id factice « /0/ » (`{% url '<app>:card_html' 0 %}`) ; les
   *  gabarits communs l'émettent sur l'entrée de file (`data-card-url`, `_queue_entry.html`).
   *  Les 10 vues `card_html` répondent du HTML depuis le 2026-09-15 (l'imager répondait du JSON).
   *  Écrite pour la suppression d'une card de lot sans rechargement de la page ; les copies
   *  locales de `refreshCard` (8 apps) sont à porter dessus. */
  function fetchCard(urlTemplate, id) {
    if (!urlTemplate || id == null) return Promise.resolve(null);
    return fetch(getUrl(urlTemplate, id), { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.text() : ''; })
      .then(function (html) {
        const tpl = document.createElement('template');
        tpl.innerHTML = (html || '').trim();
        return tpl.content.firstElementChild;
      })
      .catch(function () { return null; });
  }

  /** Taille LISIBLE, unité choisie selon la valeur : « 512 Ko », « 3,8 Go ».
   *
   *  Pourquoi pas « tout en Go » (question de Fabien, 2026-09-29) : les tailles de WAMA vont
   *  d'un fichier de voix de quelques Ko à un modèle de 50 Go — en Go fixe, les petites
   *  s'écrivent « 0,0 Go » ; en Mo fixe (la liste « Idle Models »), 10 Go s'écrivent « 10240 MB ».
   *  `from` dit l'unité de la valeur REÇUE, pour que l'appelant n'ait pas à reconvertir ce que
   *  le serveur envoie déjà en Mo ou en Go. Base 1024, comme les valeurs VRAM du serveur.
   *  Unités en français : c'est un texte affiché (règle de langue d'AGENTS.md). */
  const SIZE_UNITS = ['o', 'Ko', 'Mo', 'Go', 'To'];
  function formatSize(value, from) {
    const n = Number(value);
    if (value == null || value === '' || !isFinite(n)) return '—';
    let i = Math.max(0, ['B', 'KB', 'MB', 'GB', 'TB'].indexOf(String(from || 'B').toUpperCase()));
    let v = Math.abs(n);
    while (v >= 1024 && i < SIZE_UNITS.length - 1) { v /= 1024; i++; }
    while (v > 0 && v < 1 && i > 0) { v *= 1024; i--; }
    const digits = (v >= 100 || i === 0) ? 0 : 1;
    return (n < 0 ? '-' : '') + v.toFixed(digits).replace('.', ',').replace(/,0$/, '')
      + ' ' + SIZE_UNITS[i];
  }

  global.WamaApp = {
    formatSize: formatSize,
    escapeHtml: escapeHtml,
    getUrl: getUrl,
    csrfHeaders: csrfHeaders,
    csrfFetch: csrfFetch,
    csrfToken: csrfToken,
    jsonOrExplain: jsonOrExplain,
    wordCount: wordCount,
    Poller: Poller,
    emptyState: emptyState,
    toast: toast,
    ask: ask,
    filesFromServerPaths: filesFromServerPaths,
    injectFiles: injectFiles,
    designateInto: designateInto,
    designationOf: designationOf,
    clearDesignation: clearDesignation,
    appendFile: appendFile,
    appendInput: appendInput,
    pickFromLibrary: pickFromLibrary,
    addToQueue: addToQueue,
    fetchCard: fetchCard,
    initUrlImport: initUrlImport,
    pauseDomMedia: pauseDomMedia,
    claimAudioChannel: claimAudioChannel,
    Speech: Speech,
    STATUS_BADGE: STATUS_BADGE,
    STATUS_LABEL: STATUS_LABEL,
    normalizeStatus: normalizeStatus,
    statusLabel: statusLabel,
    statusBadge: statusBadge,
  };

  // ══ NOTIFICATIONS EN DIRECT (2026-10-03, question de Fabien) ═══════════════════════════════
  // La cloche de l'en-tête ne comptait les non lues qu'AU CHARGEMENT de la page, et rien ne
  // prévenait d'une notification arrivée pendant qu'on travaille. Ici, pour TOUTES les
  // notifications (demande d'accès, card transférée, worker arrêté…) : la cloche se met à jour,
  // et chaque NOUVELLE notification s'affiche en bas à droite avec son lien. Le dernier id vu est
  // gardé (localStorage) : une notification arrivée entre deux pages s'affiche à la suivante, une
  // déjà montrée ne revient pas. Route absente (avant relance) ou session perdue : silence.
  const NOTIF_EVERY_MS = 60000;
  const NOTIF_KEY = 'wama.notifications.lastSeen';

  function notifBell() {
    return (typeof document !== 'undefined' && document.getElementById)
      ? document.getElementById('wamaNotificationsLink') : null;
  }

  function setBellCount(n) {
    const bell = notifBell();
    if (!bell) return;
    let badge = bell.querySelector('.badge');
    if (!n) { if (badge) badge.remove(); return; }
    if (!badge) {
      badge = document.createElement('span');
      badge.className = 'position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger';
      badge.style.fontSize = '.6rem';
      bell.appendChild(badge);
    }
    badge.textContent = n;
    bell.title = 'Notifications — ' + n + ' non lue' + (n > 1 ? 's' : '');
  }

  function notifPopup(item) {
    let stack = document.getElementById('wama-notif-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.id = 'wama-notif-stack';
      // Au-dessus des toasts (bottom:20px) : les deux coexistent sans se recouvrir.
      stack.style.cssText = 'position:fixed;right:20px;bottom:76px;z-index:9998;display:flex;' +
        'flex-direction:column;gap:8px;max-width:380px;';
      document.body.appendChild(stack);
    }
    const el = document.createElement('div');
    el.className = 'wama-notif-popup';
    el.setAttribute('data-notification-id', item.id);
    el.style.cssText = 'background:#1e1b2e;color:#ede9fe;border:1px solid rgba(167,139,250,.55);' +
      'border-radius:8px;padding:10px 14px;box-shadow:0 6px 20px rgba(0,0,0,.45);font-size:.85rem;';
    el.innerHTML = '<div class="d-flex justify-content-between gap-2">' +
      '<b><i class="fas fa-bell me-1" style="color:#c4b5fd;"></i>' + escapeHtml(item.title) + '</b>' +
      '<button type="button" class="btn-close btn-close-white" style="font-size:.6rem;" ' +
      'aria-label="Fermer"></button></div>' +
      (item.body ? '<div class="mt-1" style="color:#ddd6fe;white-space:pre-line;">' +
        escapeHtml(item.body) + '</div>' : '') +
      '<div class="mt-2"><a href="' + escapeHtml(item.url || '/common/notifications/') +
      '" class="btn btn-sm btn-outline-light py-0">Ouvrir</a></div>';
    const close = function () { el.remove(); };
    el.querySelector('.btn-close').addEventListener('click', close);
    let timer = setTimeout(close, 20000);
    el.addEventListener('mouseenter', function () { clearTimeout(timer); });
    el.addEventListener('mouseleave', function () { timer = setTimeout(close, 8000); });
    stack.appendChild(el);
  }

  function readLastSeen() {
    try { return parseInt(localStorage.getItem(NOTIF_KEY) || '', 10); } catch (e) { return NaN; }
  }
  function writeLastSeen(id) {
    try { localStorage.setItem(NOTIF_KEY, String(id)); } catch (e) { /* stockage indisponible */ }
  }

  function checkNotifications() {
    if (!notifBell() || !global.fetch) return;
    const seen = readLastSeen();
    const q = isFinite(seen) ? ('?after=' + seen) : '';
    fetch('/common/api/notifications/recent/' + q, { headers: { 'Accept': 'application/json' } })
      .then(function (r) {
        const type = r.headers.get('content-type') || '';
        return (r.ok && type.indexOf('json') !== -1) ? r.json() : null;
      })
      .then(function (d) {
        if (!d) return;
        setBellCount(d.unread);
        // Première visite (rien de mémorisé) : on prend le point de départ sans rien montrer —
        // l'historique est sur la page Notifications, pas en rafale à l'écran.
        if (isFinite(seen)) (d.items || []).forEach(notifPopup);
        writeLastSeen(Math.max(d.last_id || 0, isFinite(seen) ? seen : 0));
      })
      .catch(function () { /* hors ligne, route absente : rien à dire */ });
  }

  function startNotifications() {
    if (!notifBell()) return;
    checkNotifications();
    setInterval(checkNotifications, NOTIF_EVERY_MS);
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') checkNotifications();
    });
  }
  global.WamaApp.checkNotifications = checkNotifications;
  if (typeof document === 'undefined' || !document.addEventListener) {
    /* hors navigateur (V8 des tests) : rien à surveiller */
  } else if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startNotifications);
  } else {
    startNotifications();
  }
})(window);
