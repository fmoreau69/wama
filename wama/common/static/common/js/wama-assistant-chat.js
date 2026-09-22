/*
 * WamaAssistantChat — le mini-chat de l'assistant dans le volet droit, sur TOUTE page.
 *
 * POURQUOI (Fabien, 2026-09-22 : « dialoguer avec l'assistant dans tout WAMA, avec un peu moins
 * de paramétrage que depuis la page d'accueil pour ne pas trop consommer de place »). Le FIL
 * est celui de l'accueil (surface `web`, tenu côté serveur) : ce qu'on dit ici se retrouve là,
 * et réciproquement. Les RÉGLAGES (modèle, curseur, voix choisie) restent ceux de l'accueil,
 * durables — le volet n'en montre qu'un rappel en lecture seule (étiquette du dernier tour).
 * La VOIX est la brique commune `WamaAssistantVoice` (même bouton, même comportement).
 *
 * Auto-monté sur `#assistant-chat` (rendu par `common/_assistant_avatar.html`, base.html) ;
 * inerte ailleurs. Sur l'accueil le partial ne rend pas ce bloc (le chat complet est là).
 *
 * Champ de saisie : une ligne, qui GRANDIT jusqu'à 4 lignes puis défile ; Entrée envoie,
 * Maj+Entrée saute une ligne. Fil : borné en hauteur, défile, chargé à la demande (une
 * requête au montage, `/api/ai-chat/thread/`).
 */
(function (global) {
  'use strict';

  var INPUT_MAX_HEIGHT_PX = 96;
  var root, feed, input, sendBtn, statusEl, cfg;

  function csrfToken() {
    if (global.WamaApp && global.WamaApp.csrfToken) return global.WamaApp.csrfToken();
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  function escapeHtml(text) {
    return String(text || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Sous-ensemble de Markdown, sûr : gras, liens http(s), sauts de ligne — comme l'accueil.
  function toHtml(text) {
    var h = escapeHtml(text);
    h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>');
    return h.replace(/\n/g, '<br>');
  }

  function bubble(content, role) {
    var div = document.createElement('div');
    div.className = 'wama-assistant-msg wama-assistant-msg-' + role;
    if (role === 'assistant') div.innerHTML = toHtml(content);
    else div.textContent = content;
    return div;
  }

  function toolSteps(steps) {
    var div = document.createElement('div');
    div.className = 'wama-assistant-steps';
    (steps || []).forEach(function (step) {
      var line = document.createElement('div');
      var failed = step.result && step.result.error;
      line.textContent = (failed ? '❌ ' : '✅ ') + step.tool;
      line.title = failed ? String(step.result.error) : '';
      div.appendChild(line);
    });
    return div;
  }

  function scrollToEnd() {
    feed.scrollTop = feed.scrollHeight;
  }

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text || '';
  }

  function render(entries) {
    feed.innerHTML = '';
    var last = null;
    (entries || []).forEach(function (entry) {
      if (entry.type === 'tool_steps') feed.appendChild(toolSteps(entry.steps));
      else if (entry.type === 'user') feed.appendChild(bubble(entry.content, 'user'));
      else if (entry.type === 'assistant') { feed.appendChild(bubble(entry.content, 'assistant')); last = entry.model || last; }
      else if (entry.type === 'error') feed.appendChild(bubble(entry.content, 'error'));
    });
    if (!entries || !entries.length) {
      var empty = document.createElement('div');
      empty.className = 'wama-assistant-empty';
      empty.textContent = cfg.greeting || 'Posez une question à l’assistant.';
      feed.appendChild(empty);
    }
    if (last) setStatus(last);
    scrollToEnd();
  }

  function loadThread() {
    if (!cfg.threadUrl) return;
    fetch(cfg.threadUrl, { headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.json(); })
      .then(function (data) { render(data.entries || []); })
      .catch(function () { render([]); });
  }

  function autoGrow() {
    input.style.height = 'auto';
    var h = Math.min(input.scrollHeight, INPUT_MAX_HEIGHT_PX);
    input.style.height = h + 'px';
    input.style.overflowY = input.scrollHeight > INPUT_MAX_HEIGHT_PX ? 'auto' : 'hidden';
  }

  function send() {
    var message = (input.value || '').trim();
    if (!message || input.disabled) return;
    var placeholder = feed.querySelector('.wama-assistant-empty');
    if (placeholder) placeholder.remove();
    feed.appendChild(bubble(message, 'user'));
    input.value = ''; autoGrow();
    input.disabled = true; sendBtn.disabled = true;
    var waiting = document.createElement('div');
    waiting.className = 'wama-assistant-msg wama-assistant-msg-assistant wama-assistant-waiting';
    waiting.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    feed.appendChild(waiting); scrollToEnd();
    if (global.WamaAssistantVoice) global.WamaAssistantVoice.stop();
    fetch(cfg.chatUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: JSON.stringify({ message: message }),
    }).then(function (r) { return r.json(); }).then(function (data) {
      waiting.remove();
      if (data.success) {
        if (data.tool_steps && data.tool_steps.length) feed.appendChild(toolSteps(data.tool_steps));
        feed.appendChild(bubble(data.response, 'assistant'));
        if (data.model) setStatus(data.model);
        if (global.WamaAssistantVoice) global.WamaAssistantVoice.speak(data.response);
      } else {
        feed.appendChild(bubble(data.error || data.response || 'Erreur', 'error'));
      }
    }).catch(function (e) {
      waiting.remove();
      feed.appendChild(bubble('Erreur réseau : ' + e.message, 'error'));
    }).then(function () {
      input.disabled = false; sendBtn.disabled = false; scrollToEnd(); input.focus();
    });
  }

  function mount() {
    root = document.getElementById('assistant-chat');
    if (!root) return;
    cfg = {
      chatUrl: root.dataset.chatUrl, threadUrl: root.dataset.threadUrl,
      greeting: root.dataset.greeting || '',
    };
    feed = root.querySelector('.wama-assistant-feed');
    input = root.querySelector('textarea');
    sendBtn = root.querySelector('[data-assistant-send]');
    statusEl = root.querySelector('.wama-assistant-status');
    input.addEventListener('input', autoGrow);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    });
    sendBtn.addEventListener('click', send);
    if (global.WamaAssistantVoice) global.WamaAssistantVoice.bindButton(root.querySelector('[data-assistant-voice]'));
    autoGrow();
    loadThread();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();

  global.WamaAssistantChat = { send: send, reload: loadThread };
})(window);
