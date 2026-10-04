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
    this.autoGrow();
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
  Chat.prototype.send = function () {
    var message = (this.input.value || '').trim();
    if (!message || this.input.disabled) return;
    this.dropGreeting();
    this.feed.appendChild(this.bubble(message, 'user'));
    this.input.value = '';
    this.autoGrow();
    this.busy(true);
    this.startWaiting();
    if (global.WamaAssistantVoice) global.WamaAssistantVoice.stop();
    var self = this;
    var tour = this.cfg.streamUrl ? this.sendStreaming(message) : this.sendBlocking(message);
    tour.catch(function (e) {
      self.stopWaiting();
      self.feed.appendChild(self.bubble('Erreur réseau : ' + e.message, 'error'));
    }).then(function () {
      self.busy(false);
      self.scrollToEnd();
      self.input.focus();
    });
  };

  Chat.prototype.busy = function (on) {
    this.input.disabled = on;
    this.sendBtn.disabled = on;
  };

  /** Un résultat d'outil peut demander à la SURFACE de faire quelque chose — aujourd'hui
   *  basculer le mode d'UI (`switch_ui_mode`). Le pont existe depuis l'accueil ; il vaut
   *  désormais pour les deux densités, puisque c'est la même brique. */
  Chat.prototype.applyActions = function (steps) {
    (steps || []).forEach(function (step) {
      var r = step && step.result;
      if (r && r.action === 'switch_mode' && global.wamaSetMode) global.wamaSetMode(r.mode, false);
    });
  };

  Chat.prototype.sendBlocking = function (message) {
    var self = this;
    return fetch(this.cfg.chatUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: JSON.stringify({ message: message }),
    }).then(function (r) {
      // ⚠ Brique commune : un 502/504 rend du HTML, et `response.json()` seul faisait lire
      // « Unexpected token '<' » à l'utilisateur au lieu de la raison (mesuré le 23/09).
      return (global.WamaApp && global.WamaApp.jsonOrExplain)
        ? global.WamaApp.jsonOrExplain(r) : r.json();
    }).then(function (data) {
      self.stopWaiting();
      if (data.success === false || (!data.success && data.error)) {
        self.feed.appendChild(self.bubble(data.error || 'Erreur', 'error'));
        return;
      }
      if (data.tool_steps && data.tool_steps.length) {
        self.feed.appendChild(self.toolSteps(data.tool_steps));
        self.applyActions(data.tool_steps);
      }
      self.feed.appendChild(self.bubble(data.response, 'assistant', data.model));
      if (data.model) self.setStatus(data.model);
      if (global.WamaAssistantVoice) global.WamaAssistantVoice.speak(data.response);
    });
  };

  /**
   * Tour EN FLUX. La bulle de réponse naît vide et se remplit ; la voix suit au fil des phrases.
   * ⚠ C'est l'événement `done` qui FAIT FOI : il porte la réponse complète et l'étiquette du
   * modèle, donc l'affichage se réaligne dessus. Sans ce recalage, un fragment perdu laisserait
   * à l'écran un texte différent de celui qui est enregistré dans le fil.
   */
  Chat.prototype.sendStreaming = function (message) {
    var self = this;
    if (!global.fetch || !global.ReadableStream || !global.TextDecoder) {
      return this.sendBlocking(message);
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
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: JSON.stringify({ message: message }),
    }).then(function (resp) {
      var type = resp.headers.get('Content-Type') || '';
      // Le serveur n'a pas ouvert de flux (garde GPU, erreur, route absente) : on retombe sur
      // le tour synchrone plutôt que d'échouer — le repli est la raison d'être de ce test.
      if (!resp.ok || type.indexOf('text/event-stream') === -1) {
        if (voix) voix.end();
        return self.sendBlocking(message);
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
          if (r.error) { self.feed.appendChild(self.bubble(r.error, 'error')); return; }
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
      return pomper().then(function () { if (voix) voix.end(); });
    });
  };

  // ── Montage ──────────────────────────────────────────────────────────────────
  var instances = [];

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
  };
})(window);
