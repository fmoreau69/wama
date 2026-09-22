/*
 * WamaAssistantVoice — la VOIX de l'assistant, brique commune (accueil + volet droit).
 *
 * POURQUOI. Jusqu'au 2026-09-22 la vocalisation (nettoyage du Markdown, découpage en phrases,
 * appel `/api/tts-kokoro/`, lecture par l'avatar ou par le canal commun) vivait dans `home.html`,
 * et « voix activée » n'était qu'une clé de `localStorage`. Le mini-chat du volet (toutes les
 * pages) devait parler exactement pareil : c'est donc ici, une fois. Demande de Fabien : un
 * bouton UNIQUE qui, pendant une lecture, l'ARRÊTE, et sinon coupe/rétablit la voix (muet) —
 * « actuellement, quand une lecture est active, on ne peut pas l'arrêter ».
 *
 * CONTRAT.
 *   configure({enabled, voice, lang, settingsUrl}) : état initial (préférence DURABLE `voice`
 *       de l'assistant, rendue en data-* par base.html ; `voice` = nom Kokoro, vide = voix de
 *       la langue du profil, choisie côté serveur).
 *   speak(text)      : vocalise (par phrases, la suivante demandée pendant la lecture) — si la
 *       voix est activée ; rend une Promise résolue à la fin.
 *   stop()           : coupe la lecture en cours (canal commun ET avatar).
 *   setEnabled(on)   : muet / actif, PERSISTÉ par la même route que les réglages de l'assistant.
 *   bindButton(btn)  : câble le bouton à trois états — ⏹ pendant une lecture (clic = arrêter),
 *       🔊 voix active (clic = muet), 🔇 muet (clic = réactiver). Plusieurs boutons peuvent
 *       être câblés (accueil + volet) : ils reflètent le même état.
 *
 * Ce qui reste hors d'ici : le CHOIX de la voix (sélecteur de l'accueil, qui passe `voice`) et
 * le rendu 3D (`wama-avatar.js`, auquel on confie l'audio quand il est prêt).
 */
(function (global) {
  'use strict';

  var CHUNK_MIN_CHARS = 60;
  var state = { enabled: true, speaking: false, voice: '', lang: 'fr', settingsUrl: '' };
  var listeners = [];
  var avatarPoll = null;

  function csrfToken() {
    if (global.WamaApp && global.WamaApp.csrfToken) return global.WamaApp.csrfToken();
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  function notify() {
    listeners.forEach(function (fn) { try { fn(state); } catch (_) {} });
  }

  function persist(values) {
    if (!state.settingsUrl) return Promise.resolve();
    return fetch(state.settingsUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: JSON.stringify(values),
    }).catch(function () {});
  }

  function stripMarkdown(text) {
    return String(text || '')
      .replace(/```[\s\S]*?```/g, ' (bloc de code) ')
      .replace(/`[^`]+`/g, '')
      .replace(/\*\*(.+?)\*\*/g, '$1')
      .replace(/\*(.+?)\*/g, '$1')
      .replace(/#+\s+/g, '')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .replace(/^\s*[-*>]\s+/gm, '')
      .trim();
  }

  // Phrases regroupées (≥ 60 caractères) : la première part au service dès la réponse reçue.
  function splitSentences(text) {
    var parts = text.split(/(?<=[.!?…])\s+(?=\S)/);
    var chunks = [], current = '';
    parts.forEach(function (part) {
      current = current ? current + ' ' + part : part;
      if (current.length >= CHUNK_MIN_CHARS) { chunks.push(current); current = ''; }
    });
    if (current) chunks.push(current);
    return chunks;
  }

  function fetchSpeech(text, signal) {
    var body = { text: text };
    if (state.voice) body.voice = state.voice;
    return fetch('/api/tts-kokoro/', {
      method: 'POST', signal: signal,
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: JSON.stringify(body),
    }).then(function (resp) { return resp.json(); }).then(function (data) {
      if (!data.audio_b64) return null;
      var binStr = atob(data.audio_b64);
      var bytes = new Uint8Array(binStr.length);
      for (var i = 0; i < binStr.length; i++) bytes[i] = binStr.charCodeAt(i);
      return new Blob([bytes], { type: 'audio/wav' });
    });
  }

  function avatarReady() {
    return !!(global.WamaAvatar && global.WamaAvatar.estPret && global.WamaAvatar.estPret());
  }

  // Un morceau : l'avatar le joue s'il est prêt (TalkingHead met en file, on enchaîne sans
  // attendre) ; sinon le canal commun, et on attend la fin.
  function playChunk(blob, text, turn) {
    if (avatarReady()) {
      return global.WamaAvatar.speak(blob, text, state.lang).then(function (ok) {
        if (ok) return;
        return playOnChannel(blob, turn);
      });
    }
    return playOnChannel(blob, turn);
  }

  function playOnChannel(blob, turn) {
    var audio = turn.play(blob);
    if (!audio) return Promise.resolve();
    return new Promise(function (resolve) {
      audio.addEventListener('ended', resolve);
      audio.addEventListener('error', resolve);
    });
  }

  function setSpeaking(on) {
    if (state.speaking === on) return;
    state.speaking = on;
    notify();
  }

  // L'avatar joue en file : la lecture n'est finie que lorsqu'il se tait.
  function waitAvatarSilence() {
    if (!avatarReady()) return Promise.resolve();
    var head = global.WamaAvatar.instance && global.WamaAvatar.instance();
    if (!head) return Promise.resolve();
    return new Promise(function (resolve) {
      clearInterval(avatarPoll);
      avatarPoll = setInterval(function () {
        if (!head.isSpeaking) { clearInterval(avatarPoll); avatarPoll = null; resolve(); }
      }, 250);
    });
  }

  function stop() {
    if (global.WamaApp && global.WamaApp.Speech) global.WamaApp.Speech.stop();
    if (global.WamaAvatar && global.WamaAvatar.stop) global.WamaAvatar.stop();
    clearInterval(avatarPoll); avatarPoll = null;
    setSpeaking(false);
  }

  // `options.force` : lire même en muet — le bouton « Écouter » d'un message est un geste
  // explicite, pas une lecture automatique.
  function speak(text, options) {
    if (!state.enabled && !(options && options.force)) return Promise.resolve(false);
    var clean = stripMarkdown(text);
    if (!clean || !global.WamaApp || !global.WamaApp.Speech) return Promise.resolve(false);
    var turn = global.WamaApp.Speech.claim();
    if (global.WamaAvatar && global.WamaAvatar.stop) global.WamaAvatar.stop();
    var chunks = splitSentences(clean);
    setSpeaking(true);
    var pending = fetchSpeech(chunks[0], turn.signal);
    var i = 0;
    function next() {
      return pending.then(function (blob) {
        if (!turn.valid()) return false;                    // un tour plus récent a pris la main
        if (i + 1 < chunks.length) pending = fetchSpeech(chunks[i + 1], turn.signal);
        var play = blob ? playChunk(blob, chunks[i], turn) : Promise.resolve();
        return play.then(function () {
          if (!turn.valid()) return false;
          i += 1;
          return i < chunks.length ? next() : waitAvatarSilence().then(function () { return true; });
        });
      });
    }
    return next().catch(function (e) {
      if (e && e.name !== 'AbortError') console.error('[WamaAssistantVoice]', e);
      return false;
    }).then(function (done) {
      if (turn.valid()) setSpeaking(false);
      return done;
    });
  }

  function setEnabled(on, options) {
    state.enabled = !!on;
    if (!state.enabled) stop();
    notify();
    if (!options || options.persist !== false) return persist({ voice: state.enabled });
    return Promise.resolve();
  }

  function renderButton(btn) {
    var icon = btn.querySelector('i') || btn;
    icon.className = 'fas ' + (state.speaking ? 'fa-stop' : (state.enabled ? 'fa-volume-up' : 'fa-volume-mute'));
    btn.classList.toggle('btn-outline-info', state.enabled && !state.speaking);
    btn.classList.toggle('btn-outline-warning', state.speaking);
    btn.classList.toggle('btn-outline-secondary', !state.enabled && !state.speaking);
    btn.title = state.speaking ? 'Arrêter la lecture'
      : (state.enabled ? 'Couper la voix (muet)' : 'Activer la voix');
  }

  function bindButton(btn) {
    if (!btn) return;
    btn.addEventListener('click', function () {
      if (state.speaking) { stop(); return; }
      setEnabled(!state.enabled);
    });
    listeners.push(function () { renderButton(btn); });
    renderButton(btn);
  }

  function configure(opts) {
    opts = opts || {};
    if (opts.enabled !== undefined) state.enabled = !!opts.enabled;
    if (opts.voice !== undefined) state.voice = opts.voice || '';
    if (opts.lang) state.lang = opts.lang;
    if (opts.settingsUrl !== undefined) state.settingsUrl = opts.settingsUrl || '';
    notify();
  }

  global.WamaAssistantVoice = {
    configure: configure,
    speak: speak,
    stop: stop,
    setEnabled: setEnabled,
    isEnabled: function () { return state.enabled; },
    isSpeaking: function () { return state.speaking; },
    bindButton: bindButton,
    onChange: function (fn) { listeners.push(fn); },
    stripMarkdown: stripMarkdown,
    splitSentences: splitSentences,
  };
})(window);
