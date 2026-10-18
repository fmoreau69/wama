/*
 * WamaAssistantChat — LE chat de l'assistant, partout dans WAMA.
 *
 * POURQUOI UNE SEULE BRIQUE. Jusqu'au 2026-09-26 deux codes affichaient la MÊME conversation :
 * ~200 lignes écrites dans le gabarit de l'accueil, et cette brique pour le volet droit. Deux
 * rendus d'un seul fil, donc deux endroits où corriger une bulle, deux façons de vocaliser, et
 * la certitude qu'ils divergent. Demande de Fabien (26/09) : « une brique commune complète qui
 * conserve bien les améliorations pour la vocalisation, et la porter sur la page d'accueil ».
 *
 * DEUX DENSITÉS, UN SEUL COMPORTEMENT (`data-density`) :
 *   • `full`    — l'accueil : bulles larges, badge du modèle, bouton « Écouter » par réponse,
 *                 étapes d'outils dépliables avec leur résultat, mot d'attente déclaré ;
 *   • `compact` — le volet droit : le même fil, en 330 px de large.
 * Ce qui change est de l'APPARENCE. Le fil, les gardes, la voix et le flux sont identiques —
 * c'est précisément ce que deux implémentations ne pouvaient pas garantir.
 *
 * LE FLUX (levier 5, `WAMA_LLM §1bis`). Si `data-stream-url` est déclarée, le tour passe par
 * SSE : la réponse s'écrit au fur et à mesure, les étapes d'outils apparaissent dès qu'elles
 * sont jouées, et la VOIX commence à la première phrase achevée au lieu d'attendre la fin.
 * ⚠ Repli AUTOMATIQUE sur le POST classique si le navigateur ne sait pas lire un flux, si le
 * serveur répond autre chose, ou si la connexion casse en route : le tour synchrone reste le
 * chemin de référence, jamais une voie morte.
 *
 * LA VOCALISATION N'EST PAS ICI. Elle est dans `wama-assistant-voice.js`, qui appelle le
 * service TTS — lequel applique côté SERVEUR le nettoyage qui compte (retrait des emojis,
 * respirations sur les fins de ligne et les incises, tableaux aplatis : `views._clean_text_for_tts`
 * et `_rendre_audible`). Cette brique ne fait que LUI DONNER le texte, entier ou au fil du flux.
 */
(function (global) {
  'use strict';

  var INPUT_MAX_HEIGHT_PX = 96;
  //: Sans lecture vocale (voix coupée), délai avant d'ouvrir la page demandée (`open_page`) :
  //: le temps de lire la réponse — elle reste dans le fil, rechargé sur la page suivante.
  var NAVIGATE_DELAY_MS = 1500;

  /** Un chemin de CETTE instance (`/anonymizer/`) — jamais une adresse externe ni `//hôte` :
   *  une page ouverte par un résultat d'outil ne doit pas pouvoir quitter WAMA. */
  function isLocalPath(url) {
    return typeof url === 'string' && url.charAt(0) === '/' && url.charAt(1) !== '/'
      && url.charAt(1) !== '\\';
  }

  //: Icône par outil — confort de lecture des étapes. Un outil absent prend l'icône générique :
  //: la table n'a donc jamais besoin d'être exhaustive, et un outil neuf ne casse rien.
  var TOOL_ICONS = {
    list_user_files: '📂', add_to_anonymizer: '➕', start_anonymizer: '▶️',
    get_anonymizer_status: '📊', sam3_examples: '💡', create_image: '🎨',
    start_imager: '▶️', get_imager_status: '📊', add_to_enhancer: '✨',
    start_enhancer: '▶️', get_enhancer_status: '📊', add_to_audio_enhancer: '🎙️',
    start_audio_enhancer: '▶️', get_audio_enhancer_status: '📊', synthesize_text: '🗣️',
    start_synthesizer: '▶️', get_synthesizer_status: '📊', add_to_describer: '🔍',
    start_describer: '▶️', get_describer_status: '📊', add_to_transcriber: '🎤',
    start_transcriber: '▶️', get_transcriber_status: '📊', add_to_reader: '📄',
    start_reader: '▶️', get_reader_status: '📊', list_media_assets: '🗃️',
    get_media_asset_url: '🔗', charger_competence: '🎓', ask_claude_code: '🧑‍💻',
    find_user_files: '🔎', remember_fact: '🧠', open_page: '🧭',
  };

  function csrfToken() {
    if (global.WamaApp && global.WamaApp.csrfToken) return global.WamaApp.csrfToken();
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  function escapeHtml(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Sous-ensemble de Markdown, SÛR : on échappe d'abord, on enrichit ensuite, et seuls les
  // liens http(s) deviennent cliquables.
  function toHtml(text) {
    var h = escapeHtml(text);
    h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>');
    return h.replace(/\n/g, '<br>');
  }

  function Chat(root) {
    this.root = root;
    this.cfg = {
      density: root.dataset.density || 'compact',
      chatUrl: root.dataset.chatUrl,
      streamUrl: root.dataset.streamUrl || '',
      threadUrl: root.dataset.threadUrl || '',
      threadEl: root.dataset.threadEl || '',
      clearUrl: root.dataset.clearUrl || '',
      followUpsUrl: root.dataset.followUpsUrl || '',
      settingsUrl: root.dataset.settingsUrl || '',
      paramsScript: root.dataset.paramsScript || '',
      greeting: root.dataset.greeting || '',
      greetingHtml: root.dataset.greetingHtml || '',
      waiting: root.dataset.waiting || '',
      waitingAfterMs: parseInt(root.dataset.waitingAfterMs || '0', 10),
    };
    this.full = this.cfg.density === 'full';
    this.feed = root.querySelector('[data-assistant-feed]');
    this.input = root.querySelector('textarea');
    this.sendBtn = root.querySelector('[data-assistant-send]');
    this.statusEl = root.querySelector('[data-assistant-status]');
    this.waitTimer = null;
    this.deposits = [];               // fichiers GLISSÉS sur le chat, en attente d'envoi
    this.bind();
    this.loadThread();
  }

  Chat.prototype.bind = function () {
    var self = this;
    this.input.addEventListener('input', function () { self.autoGrow(); });
    this.input.addEventListener('keydown', function (e) {
      // Entrée envoie, Maj+Entrée saute une ligne — même geste dans les deux densités.
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); self.send(); }
    });
    this.sendBtn.addEventListener('click', function () { self.send(); });
    var form = this.root.querySelector('form');
    if (form) form.addEventListener('submit', function (e) { e.preventDefault(); self.send(); });
    if (global.WamaAssistantVoice) {
      global.WamaAssistantVoice.bindButton(this.root.querySelector('[data-assistant-voice]'));
    }
    var gear = this.root.querySelector('[data-assistant-settings]');
    if (gear) gear.addEventListener('click', function () { self.openSettings(); });
    this.bindDeposit();
    this.autoGrow();
  };

  // ── Réglages : la modale ⚙ COMMUNE des apps (2026-10-18) ──────────────────────
  // Le même schéma que la section « Paramètres » du volet de l'accueil (`assistant/params.py`,
  // contexte `item` pour la modale), lu par la route de réglages (GET : schéma, groupes,
  // valeurs) et enregistré par elle (POST du formulaire de `WamaParams.settingsModal`). C'est le
  // chemin du mode simplifié — volets masqués — et du mini-chat des autres pages, qui n'avait
  // aucun accès aux réglages. `wama-params.js` n'est pas global (chaque surface qui rend un
  // schéma le charge) : chargé ici à la première ouverture.
  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var tag = document.createElement('script');
      tag.src = src;
      tag.onload = resolve;
      tag.onerror = function () { reject(new Error('script ' + src)); };
      document.head.appendChild(tag);
    });
  }

  Chat.prototype.openSettings = function () {
    var url = this.cfg.settingsUrl;
    if (!url) return Promise.resolve(null);
    var ready = global.WamaParams ? Promise.resolve()
      : (this.cfg.paramsScript ? loadScript(this.cfg.paramsScript) : Promise.reject(new Error('WamaParams')));
    return ready.then(function () {
      return fetch(url, { headers: { 'Accept': 'application/json' } });
    }).then(function (r) { return r.json(); }).then(function (d) {
      return global.WamaParams.settingsModal({
        id: 'Assistant', title: "Réglages de l'assistant", titleIcon: 'fa-gear',
        schema: d.schema, groups: d.groups, values: d.values, context: 'item',
        saveUrl: url, csrf: csrfToken(),
        // Le volet de l'accueil, s'il est rendu, se recale sur ce qui vient d'être enregistré.
        onSaved: function () {
          if (document.dispatchEvent && global.CustomEvent) {
            document.dispatchEvent(new CustomEvent('wama:assistant-settings'));
          }
        },
      });
    }).catch(function () {
      if (global.WamaApp && global.WamaApp.toast) global.WamaApp.toast('Réglages indisponibles', 'error');
    });
  };

  // ── Fichiers GLISSÉS sur le chat (2026-10-18, le geste de Discord) ───────────────────
  // Déposés dans l'espace de l'utilisateur par le geste PARTAGÉ (`WamaFM.upload` →
  // `/filemanager/api/upload/` → `enregistrer_fichier_utilisateur`, celui de Discord et de l'API),
  // montrés en pastilles sous la saisie, puis envoyés AVEC le message (ou seuls : le serveur fait
  // demander « Que puis-je en faire ? », `assistant_engine.message_with_deposits`). L'assistant
  // inspecte et propose : fichier de travail, de référence, lot, RAG…
  Chat.prototype.bindDeposit = function () {
    var self = this;
    var root = this.root;
    root.addEventListener('dragover', function (e) {
      if (!e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') === -1) return;
      e.preventDefault();
      root.classList.add('wama-assistant-dragover');
    });
    root.addEventListener('dragleave', function (e) {
      if (!root.contains(e.relatedTarget)) root.classList.remove('wama-assistant-dragover');
    });
    root.addEventListener('drop', function (e) {
      if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;
      e.preventDefault();
      root.classList.remove('wama-assistant-dragover');
      self.deposit(Array.prototype.slice.call(e.dataTransfer.files));
    });
  };

  Chat.prototype.deposit = function (files) {
    var self = this;
    if (!files.length || !global.WamaFM || !global.WamaFM.upload) return Promise.resolve([]);
    this.setStatus('Dépôt de ' + files.length + ' fichier(s)…');
    return global.WamaFM.upload(files, csrfToken()).then(function (d) {
      var uploaded = (d && d.uploaded) || [];
      uploaded.forEach(function (u) { self.deposits.push({ path: u.path, name: u.name }); });
      self.renderDeposits();
      self.setStatus(uploaded.length ? '' : ('Dépôt impossible : ' + ((d && d.error) || 'erreur')));
      self.input.focus();
      return uploaded;
    }).catch(function () { self.setStatus('Dépôt impossible : erreur réseau'); return []; });
  };

  Chat.prototype.renderDeposits = function () {
    var self = this;
    if (!this.depositsEl) {
      this.depositsEl = document.createElement('div');
      this.depositsEl.className = 'wama-assistant-deposits';
      var row = this.input.parentNode;
      row.parentNode.insertBefore(this.depositsEl, row);
    }
    this.depositsEl.innerHTML = '';
    this.deposits.forEach(function (d, i) {
      var chip = document.createElement('span');
      chip.className = 'badge bg-secondary me-1 mb-1 wama-assistant-deposit';
      chip.title = d.path;
      chip.textContent = '📎 ' + d.name + ' ';
      var x = document.createElement('button');
      x.type = 'button';
      x.className = 'btn-close btn-close-white ms-1';
      x.style.fontSize = '.6em';
      x.title = 'Ne pas joindre';
      x.addEventListener('click', function () { self.deposits.splice(i, 1); self.renderDeposits(); });
      chip.appendChild(x);
      self.depositsEl.appendChild(chip);
    });
    this.depositsEl.hidden = !this.deposits.length;
  };

  Chat.prototype.autoGrow = function () {
    this.input.style.height = 'auto';
    var h = Math.min(this.input.scrollHeight, INPUT_MAX_HEIGHT_PX);
    this.input.style.height = h + 'px';
    this.input.style.overflowY = this.input.scrollHeight > INPUT_MAX_HEIGHT_PX ? 'auto' : 'hidden';
  };

  Chat.prototype.scrollToEnd = function () { this.feed.scrollTop = this.feed.scrollHeight; };

  Chat.prototype.setStatus = function (text) {
    if (this.statusEl) this.statusEl.textContent = text || '';
  };

  // ── Rendu ────────────────────────────────────────────────────────────────────
  Chat.prototype.bubble = function (content, role, model) {
    var wrap = document.createElement('div');
    wrap.className = 'wama-assistant-line wama-assistant-line-' + role;
    var bubble = document.createElement('div');
    bubble.className = 'wama-assistant-msg wama-assistant-msg-' + role;
    if (role === 'assistant') bubble.innerHTML = toHtml(content);
    else bubble.textContent = content;
    if (this.full && role === 'assistant' && model) {
      var badge = document.createElement('div');
      badge.className = 'wama-assistant-model';
      badge.textContent = model;
      bubble.appendChild(badge);
    }
    wrap.appendChild(bubble);
    // « Écouter » : un geste EXPLICITE, donc il lit même quand la voix est coupée.
    if (this.full && role === 'assistant') {
      var self = this;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-sm btn-link text-secondary p-0 ms-1 align-top';
      btn.title = 'Écouter';
      btn.innerHTML = '<i class="fas fa-volume-up" style="font-size:.8em"></i>';
      btn.addEventListener('click', function () {
        if (global.WamaAssistantVoice) {
          global.WamaAssistantVoice.speak(self.textOf(bubble), { force: true });
        }
      });
      wrap.appendChild(btn);
    }
    return wrap;
  };

  /** Bulle d'ERREUR d'un tour. Le modèle CHOISI est saturé (2026-10-13) : le serveur PROPOSE le
   *  relais que le choix automatique prendrait (`fallback`) — un clic renvoie le même message
   *  avec ce modèle, pour ce message seul ; le réglage de l'utilisateur ne change pas. */
  Chat.prototype.errorBubble = function (result, message) {
    var line = this.bubble((result && result.error) || 'Erreur', 'error');
    var relay = result && result.fallback;
    var files = this.lastFiles || [];        // le relais renvoie aussi les fichiers déposés
    if (relay && relay.model_key && message) {
      var self = this;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-sm btn-outline-secondary ms-2 align-top';
      btn.textContent = 'Répondre avec ' + (relay.label || relay.model_key);
      btn.addEventListener('click', function () {
        btn.disabled = true;
        self.send({ message: message, model: relay.model_key, files: files });
      });
      line.appendChild(btn);
    }
    return line;
  };

  Chat.prototype.textOf = function (bubble) {
    var clone = bubble.cloneNode(true);
    var badge = clone.querySelector('.wama-assistant-model');
    if (badge) badge.remove();
    return clone.innerText || clone.textContent || '';
  };

  Chat.prototype.toolSteps = function (steps) {
    var div = document.createElement('div');
    div.className = 'wama-assistant-steps';
    var full = this.full;
    (steps || []).forEach(function (step) {
      var icon = TOOL_ICONS[step.tool] || '🔧';
      var failed = !!(step.result && step.result.error);
      if (!full) {
        var line = document.createElement('div');
        line.className = failed ? 'wama-assistant-step-ko' : '';
        line.textContent = icon + ' ' + step.tool + (failed ? ' ❌' : ' ✅');
        if (failed) line.title = String(step.result.error);
        div.appendChild(line);
        return;
      }
      // Densité pleine : le résultat est consultable, replié par défaut.
      var details = document.createElement('details');
      var summary = document.createElement('summary');
      summary.className = failed ? 'wama-assistant-step-ko' : '';
      summary.textContent = failed
        ? icon + ' ' + step.tool + ' → ❌ ' + step.result.error
        : icon + ' ' + step.tool + ' → ✅';
      var pre = document.createElement('pre');
      pre.textContent = JSON.stringify(step.result, null, 2);
      details.appendChild(summary);
      details.appendChild(pre);
      div.appendChild(details);
    });
    return div;
  };

  /** L'accueil DÉCLARÉ. Un `<template>` plutôt qu'un attribut : le message de bienvenue est
   *  rendu par le serveur (il VARIE selon l'état de connexion) et peut contenir des liens ;
   *  le faire transiter par un attribut `data-` imposerait un double échappement fragile. */
  Chat.prototype.showGreeting = function () {
    var empty = document.createElement('div');
    empty.className = 'wama-assistant-empty';
    var modele = this.root.querySelector('template[data-assistant-greeting]');
    if (modele) empty.appendChild(modele.content.cloneNode(true));
    else empty.textContent = this.cfg.greeting || 'Posez une question à l’assistant.';
    this.feed.appendChild(empty);
  };

  Chat.prototype.dropGreeting = function () {
    var placeholder = this.feed.querySelector('.wama-assistant-empty');
    if (placeholder) placeholder.remove();
  };

  Chat.prototype.render = function (entries) {
    var self = this;
    this.feed.innerHTML = '';
    var lastModel = null;
    (entries || []).forEach(function (entry) {
      if (entry.type === 'tool_steps') self.feed.appendChild(self.toolSteps(entry.steps));
      else if (entry.type === 'user') self.feed.appendChild(self.bubble(entry.content, 'user'));
      else if (entry.type === 'assistant') {
        self.feed.appendChild(self.bubble(entry.content, 'assistant', entry.model));
        lastModel = entry.model || lastModel;
      } else if (entry.type === 'error') self.feed.appendChild(self.bubble(entry.content, 'error'));
    });
    if (!entries || !entries.length) this.showGreeting();
    if (lastModel) this.setStatus(lastModel);
    this.scrollToEnd();
  };

  Chat.prototype.loadThread = function () {
    var self = this;
    // L'accueil porte déjà son fil dans la page (`json_script`) : ne pas le redemander.
    if (this.cfg.threadEl) {
      var el = document.getElementById(this.cfg.threadEl);
      try { this.render(el ? JSON.parse(el.textContent) : []); } catch (e) { this.render([]); }
      return;
    }
    if (!this.cfg.threadUrl) { this.render([]); return; }
    fetch(this.cfg.threadUrl, { headers: { Accept: 'application/json' } })
      .then(function (r) { return r.json(); })
      .then(function (d) { self.render(d.entries || []); })
      .catch(function () { self.render([]); });
  };

  Chat.prototype.clear = function () {
    var self = this;
    var done = function () { self.feed.innerHTML = ''; self.showGreeting(); self.setStatus(''); };
    if (!this.cfg.clearUrl) { done(); return Promise.resolve(); }
    return fetch(this.cfg.clearUrl, { method: 'POST', headers: { 'X-CSRFToken': csrfToken() } })
      .catch(function () {})          // l'écran se vide quand même ; le fil revient au rechargement
      .then(done);
  };

  // ── Attente ──────────────────────────────────────────────────────────────────
  // Le mot d'attente s'affiche APRÈS un délai, tous deux DÉCLARÉS côté serveur : un modèle qui
  // se charge met plusieurs secondes et l'attente ressemble alors à une panne ; l'afficher tout
  // de suite ferait clignoter l'interface quand la réponse arrive vite.
  Chat.prototype.startWaiting = function () {
    var self = this;
    this.dropGreeting();
    var wrap = document.createElement('div');
    wrap.className = 'wama-assistant-line wama-assistant-line-assistant';
    wrap.innerHTML = '<div class="wama-assistant-msg wama-assistant-msg-assistant '
      + 'wama-assistant-waiting"><i class="fas fa-spinner fa-spin"></i>'
      + '<span class="wama-assistant-wait-word"></span></div>';
    this.feed.appendChild(wrap);
    this.waitingEl = wrap;
    this.scrollToEnd();
    if (this.cfg.waiting && this.cfg.waitingAfterMs > 0) {
      clearTimeout(this.waitTimer);
      this.waitTimer = setTimeout(function () {
        var el = wrap.querySelector('.wama-assistant-wait-word');
        if (el) el.textContent = self.cfg.waiting;
      }, this.cfg.waitingAfterMs);
    }
  };

  // DÉCOMPTE (2026-10-04) : le serveur annonce l'attente APPRISE pour le modèle retenu (ETA
  // commune, moyenne par modèle et par matériel) ; on la décompte à la place du mot d'attente.
  // Rien n'est annoncé tant que rien n'a été mesuré, ni pour une attente trop courte.
  Chat.prototype.showCountdown = function (seconds) {
    var word = this.waitingEl && this.waitingEl.querySelector('.wama-assistant-wait-word');
    if (!word || !(seconds > 0)) return;
    clearTimeout(this.waitTimer);
    clearInterval(this.countdownTimer);
    var deadline = Date.now() + seconds * 1000;
    function draw() {
      var left = Math.ceil((deadline - Date.now()) / 1000);
      word.textContent = left > 0 ? 'Réponse dans environ ' + left + ' s' : 'Encore un instant…';
    }
    draw();
    this.countdownTimer = setInterval(draw, 1000);
  };

  Chat.prototype.stopWaiting = function () {
    clearTimeout(this.waitTimer);
    clearInterval(this.countdownTimer);
    if (this.waitingEl) { this.waitingEl.remove(); this.waitingEl = null; }
  };

  // ── Envoi ────────────────────────────────────────────────────────────────────
  // Rend la PROMESSE du tour (résolue quand la réponse est écrite — pas quand elle est dite) :
  // la conversation vocale (`wama-assistant-listen.js`) enchaîne dessus. Rien à envoyer →
  // promesse résolue tout de suite.
  // `relay` ({message, model}) : renvoi d'un message avec le modèle proposé (`errorBubble`) — la
  // saisie en cours n'est pas touchée.
  Chat.prototype.send = function (relay) {
    var message = relay ? relay.message : (this.input.value || '').trim();
    // Les fichiers déposés partent avec CE message (un relais garde ceux du message relayé).
    var files = relay ? (relay.files || []) : this.deposits.map(function (d) { return d.path; });
    if ((!message && !files.length) || this.input.disabled) return Promise.resolve(false);
    this.dropGreeting();
    var names = relay ? files.map(function (p) { return p.split('/').pop(); })
      : this.deposits.map(function (d) { return d.name; });
    var shown = names.length ? names.map(function (n) { return '📎 ' + n; }).join('\n') +
      (message ? '\n' + message : '') : message;
    this.feed.appendChild(this.bubble(shown, 'user'));
    if (!relay) {
      this.input.value = '';
      this.deposits = [];
      this.renderDeposits();
      this.autoGrow();
    }
    this.lastFiles = files;
    this.busy(true);
    this.startWaiting();
    if (global.WamaAssistantVoice) global.WamaAssistantVoice.stop();
    this.controller = global.AbortController ? new AbortController() : null;
    this.pendingPage = null;          // une page retenue par un tour précédent ne se suit plus
    var self = this;
    var model = relay ? relay.model : null;
    var tour = this.cfg.streamUrl ? this.sendStreaming(message, model)
      : this.sendBlocking(message, model);
    return tour.catch(function (e) {
      self.stopWaiting();
      self.pendingPage = null;        // tour interrompu ou en échec : on ne quitte pas la page
      // Interrompu par l'utilisateur (`abort`, il a repris la parole) : pas une panne.
      if (e && e.name === 'AbortError') return;
      self.feed.appendChild(self.bubble('Erreur réseau : ' + e.message, 'error'));
    }).then(function () {
      self.controller = null;
      self.busy(false);
      self.scrollToEnd();
      self.input.focus();
      return true;
    });
  };

  /** Interrompt le tour EN COURS (requête et lecture du flux) — l'utilisateur reprend la
   *  parole. Ce qui est déjà écrit reste affiché ; le serveur, lui, peut finir son tour et
   *  l'enregistrer au fil. */
  Chat.prototype.abort = function () {
    if (this.controller) { try { this.controller.abort(); } catch (_) {} }
  };

  Chat.prototype.isBusy = function () { return !!this.controller; };

  Chat.prototype.signal = function () {
    return this.controller ? this.controller.signal : undefined;
  };

  Chat.prototype.busy = function (on) {
    this.input.disabled = on;
    this.sendBtn.disabled = on;
  };

  /** Un résultat d'outil peut demander à la SURFACE de faire quelque chose — basculer le mode
   *  d'UI (`switch_ui_mode`), ou OUVRIR UNE PAGE (`open_page`, 2026-10-11). Le pont existe
   *  depuis l'accueil ; il vaut pour les deux densités, puisque c'est la même brique.
   *  ⚠ La page n'est pas ouverte ici : quitter la page couperait la réponse et sa voix. Elle
   *  est RETENUE, puis suivie quand le tour est écrit et dit (`followPendingPage`). */
  Chat.prototype.applyActions = function (steps) {
    var self = this;
    (steps || []).forEach(function (step) {
      var r = step && step.result;
      if (!r) return;
      if (r.action === 'switch_mode' && global.wamaSetMode) global.wamaSetMode(r.mode, false);
      if (r.action === 'navigate' && isLocalPath(r.url)) self.pendingPage = r.url;
    });
  };

  /** Suit la page retenue par `applyActions` une fois `spoken` résolue (la lecture vocale
   *  finie) ; sans voix, après un court délai pour laisser lire la réponse. Le fil serveur
   *  suit : le chat de la nouvelle page le recharge (`threadUrl`). */
  Chat.prototype.followPendingPage = function (spoken) {
    var url = this.pendingPage;
    this.pendingPage = null;
    if (!url) return;
    Promise.resolve(spoken).then(function (said) {
      setTimeout(function () { global.location.assign(url); }, said ? 0 : NAVIGATE_DELAY_MS);
    });
  };

  /** Corps d'un tour : le message, le modèle imposé pour lui seul s'il y en a un, et les
   *  fichiers déposés (chemins de l'espace de l'utilisateur, `message_with_deposits`). */
  function turnBody(message, model, files) {
    var body = { message: message };
    if (model) body.model = model;
    if (files && files.length) body.files = files;
    return JSON.stringify(body);
  }

  Chat.prototype.sendBlocking = function (message, model) {
    var self = this;
    return fetch(this.cfg.chatUrl, {
      method: 'POST', signal: this.signal(),
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: turnBody(message, model, this.lastFiles),
    }).then(function (r) {
      // ⚠ Brique commune : un 502/504 rend du HTML, et `response.json()` seul faisait lire
      // « Unexpected token '<' » à l'utilisateur au lieu de la raison (mesuré le 23/09).
      return (global.WamaApp && global.WamaApp.jsonOrExplain)
        ? global.WamaApp.jsonOrExplain(r) : r.json();
    }).then(function (data) {
      self.stopWaiting();
      if (data.success === false || (!data.success && data.error)) {
        self.feed.appendChild(self.errorBubble(data, message));
        return;
      }
      if (data.tool_steps && data.tool_steps.length) {
        self.feed.appendChild(self.toolSteps(data.tool_steps));
        self.applyActions(data.tool_steps);
      }
      self.feed.appendChild(self.bubble(data.response, 'assistant', data.model));
      if (data.model) self.setStatus(data.model);
      var spoken = global.WamaAssistantVoice ? global.WamaAssistantVoice.speak(data.response) : null;
      self.followPendingPage(spoken);
    });
  };

  /**
   * Tour EN FLUX. La bulle de réponse naît vide et se remplit ; la voix suit au fil des phrases.
   * ⚠ C'est l'événement `done` qui FAIT FOI : il porte la réponse complète et l'étiquette du
   * modèle, donc l'affichage se réaligne dessus. Sans ce recalage, un fragment perdu laisserait
   * à l'écran un texte différent de celui qui est enregistré dans le fil.
   */
  Chat.prototype.sendStreaming = function (message, model) {
    var self = this;
    if (!global.fetch || !global.ReadableStream || !global.TextDecoder) {
      return this.sendBlocking(message, model);
    }
    var voix = global.WamaAssistantVoice ? global.WamaAssistantVoice.speakStream() : null;
    var bulle = null, texte = '', recu = false;

    function ecrire(fragment) {
      if (!bulle) {
        self.stopWaiting();
        var ligne = self.bubble('', 'assistant');
        bulle = ligne.querySelector('.wama-assistant-msg');
        self.feed.appendChild(ligne);
      }
      texte += fragment;
      bulle.innerHTML = toHtml(texte);
      self.scrollToEnd();
      if (voix) voix.push(fragment);
    }

    return fetch(this.cfg.streamUrl, {
      method: 'POST', signal: this.signal(),
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: turnBody(message, model, this.lastFiles),
    }).then(function (resp) {
      var type = resp.headers.get('Content-Type') || '';
      // Le serveur n'a pas ouvert de flux (garde GPU, erreur, route absente) : on retombe sur
      // le tour synchrone plutôt que d'échouer — le repli est la raison d'être de ce test.
      if (!resp.ok || type.indexOf('text/event-stream') === -1) {
        if (voix) voix.end();
        return self.sendBlocking(message, model);
      }
      var lecteur = resp.body.getReader();
      var decodeur = new TextDecoder();
      var tampon = '';

      function traiter(bloc) {
        if (bloc.indexOf('data:') !== 0) return;             // commentaire SSE (keep-alive)
        var evt;
        try { evt = JSON.parse(bloc.slice(5).trim()); } catch (e) { return; }
        if (evt.type === 'delta') { recu = true; ecrire(evt.text || ''); }
        else if (evt.type === 'eta') { self.showCountdown(evt.seconds); }
        else if (evt.type === 'step') {
          self.stopWaiting();
          self.feed.insertBefore(self.toolSteps([evt.step]), bulle ? bulle.parentNode : null);
          self.applyActions([evt.step]);
          self.scrollToEnd();
        } else if (evt.type === 'done') {
          var r = evt.result || {};
          self.stopWaiting();
          if (r.error) { self.feed.appendChild(self.errorBubble(r, message)); return; }
          if (!recu) {                                       // cloud : aucun fragment, tout arrive ici
            self.feed.appendChild(self.bubble(r.response, 'assistant', r.model));
            if (voix) voix.push(r.response || '');
          } else if (bulle) {
            texte = r.response || texte;
            bulle.innerHTML = toHtml(texte);
            if (self.full && r.model) {
              var badge = document.createElement('div');
              badge.className = 'wama-assistant-model';
              badge.textContent = r.model;
              bulle.appendChild(badge);
            }
          }
          if (r.model) self.setStatus(r.model);
        } else if (evt.type === 'error') {
          self.stopWaiting();
          self.feed.appendChild(self.bubble(evt.error || 'Erreur', 'error'));
        }
      }

      function pomper() {
        return lecteur.read().then(function (res) {
          if (res.done) return;
          tampon += decodeur.decode(res.value, { stream: true });
          var blocs = tampon.split('\n\n');
          tampon = blocs.pop();
          blocs.forEach(traiter);
          return pomper();
        });
      }
      return pomper().then(function () { self.followPendingPage(voix ? voix.end() : null); });
    });
  };

  /** Une FIN DE TÂCHE racontée dans le fil (2026-10-18) : rendue comme un tour de l'assistant —
   *  l'étape « statut » réellement jouée, puis la réponse. `speak` : ce chat la dit à voix haute
   *  (un seul des chats de la page), sauf si l'assistant parle ou répond déjà — une fin de tâche
   *  ne coupe pas une réponse en cours, elle reste écrite au fil. */
  Chat.prototype.tellFollowUp = function (followUp, speak) {
    this.dropGreeting();
    if (followUp.tool_steps && followUp.tool_steps.length) {
      this.feed.appendChild(this.toolSteps(followUp.tool_steps));
    }
    this.feed.appendChild(this.bubble(followUp.response, 'assistant', followUp.model));
    this.scrollToEnd();
    var voice = global.WamaAssistantVoice;
    if (speak && voice && !this.isBusy() && !voice.isSpeaking()) voice.speak(followUp.response);
  };

  // ── Fins de tâche : la cloche les relève, le fil les raconte (2026-10-18) ───────────────
  // Fabien : « l'assistant ne semble pas recevoir de trigger quand un travail est terminé, alors
  // qu'une notification arrive ». La cloche (`wama-app-base.js`) annonce chaque relève par
  // `wama:notifications` ; les fins de tâche y sont postées au serveur, qui raconte dans le fil
  // celles d'une tâche lancée DEPUIS ce fil (`common/services/job_follow_ups.py`, la brique de la
  // passerelle pour les canaux). Une seule demande par relève, quel que soit le nombre de chats.
  var JOB_NOTICE_KINDS = ['job_done', 'job_failed'];

  function onNotifications(evt) {
    var chat = null;
    for (var i = 0; i < instances.length; i++) {
      if (instances[i].cfg.followUpsUrl) { chat = instances[i]; break; }
    }
    if (!chat || !global.fetch) return;
    var items = (evt && evt.detail && evt.detail.items) || [];
    var ids = [];
    items.forEach(function (item) {
      if (item && JOB_NOTICE_KINDS.indexOf(item.kind) !== -1) ids.push(item.id);
    });
    if (!ids.length) return;
    fetch(chat.cfg.followUpsUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: JSON.stringify({ ids: ids }),
    }).then(function (r) { return r.ok ? r.json() : null; }).then(function (data) {
      ((data && data.follow_ups) || []).forEach(function (followUp) {
        instances.forEach(function (c) { c.tellFollowUp(followUp, c === chat); });
      });
    }).catch(function () { /* hors ligne : le fil serveur l'a gardé, il se relira */ });
  }

  // ── Montage ──────────────────────────────────────────────────────────────────
  var instances = [];
  if (document.addEventListener) document.addEventListener('wama:notifications', onNotifications);

  function mount() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-wama-chat]'), function (root) {
      if (root._wamaChat) return;
      root._wamaChat = new Chat(root);
      instances.push(root._wamaChat);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();

  global.WamaAssistantChat = {
    mount: mount,
    instances: instances,
    first: function () { return instances[0] || null; },
    // Pour les tests V8 (`tests_assistant_reach`) : les gestes du prototype s'éprouvent sans DOM.
    _Chat: Chat,
  };
})(window);
