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
 *   isAudible()      : la voix parle, ou sort encore du haut-parleur (latence de sortie).
 *   isOwnSpeech(text, heardAt) : une phrase entendue au micro n'est-elle que l'ÉCHO de ce que
 *       la voix disait ? — lu par l'écoute de la conversation (`wama-assistant-listen.js`).
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

  // ── Ce que la voix a DIT, et jusqu'à quand on l'entend (2026-10-13) ───────────────────────
  // La conversation vocale (`wama-assistant-listen.js`) a pris la fin d'une réponse pour une
  // réplique : « … si vous avez besoin d'autre chose » est reparti comme message de l'utilisateur,
  // et l'assistant s'est répondu. Le haut-parleur joue encore APRÈS la fin de l'audio (latence de
  // sortie, mesurée par le navigateur), et le micro l'entend. Ce qui tranche n'est pas
  // l'acoustique — l'annulation d'écho du navigateur ne couvre pas toujours ce que la page joue —
  // mais le TEXTE : la voix sait ce qu'elle vient de dire.
  //: Part des mots d'une phrase entendue qui doivent se retrouver, DANS L'ORDRE, dans ce que la
  //: voix vient de dire pour qu'elle soit son écho. Sous 1 : la transcription d'un écho perd ou
  //: déforme des mots ; mesuré sur l'écho du 13/10, la part était de 1.
  var ECHO_SHARE = 0.8;
  var said = { words: [], audibleUntil: 0 };    // le tour de parole en cours, ou le dernier

  function speechWords(text) {
    return String(text || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
      .split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  }

  // Le son quitte le haut-parleur après la latence de sortie : celle que l'avatar mesure.
  function markSilent() {
    var latency = avatarReady() ? global.WamaAvatar.outputLatencyMs() : 0;
    said.audibleUntil = Date.now() + latency;
  }

  /** La voix de l'assistant s'entend-elle encore ? (parle, ou sort encore du haut-parleur) */
  function isAudible() {
    return state.speaking || Date.now() < said.audibleUntil;
  }

  /**
   * `text` (une phrase entendue au micro, dont le son a commencé à `heardAt`, en ms) n'est-il que
   * l'écho de ce que la voix disait ? Il faut les DEUX : entendu pendant que la voix était
   * audible — une réponse de l'utilisateur qui reprend les mots de l'assistant APRÈS qu'il s'est
   * tu n'est pas un écho —, et fait de ses mots, dans l'ordre.
   */
  function isOwnSpeech(text, heardAt) {
    if (!said.words.length || !(heardAt <= said.audibleUntil)) return false;
    var words = speechWords(text);
    if (!words.length) return false;
    var at = 0, found = 0;
    words.forEach(function (word) {
      var index = said.words.indexOf(word, at);
      if (index >= 0) { found++; at = index + 1; }
    });
    return found / words.length >= ECHO_SHARE;
  }
  // ⚠ La page qui se DÉCHARGE abandonne les requêtes en vol, et le navigateur rend alors
  // `TypeError: Failed to fetch` — indiscernable d'un service TTS en panne si on le journalise.
  // Mesuré au smoke du 2026-09-26 : changer de page pendant une vocalisation écrivait une
  // erreur rouge en console à chaque fois. On note le départ, et on se tait à partir de là.
  var leaving = false;
  ['pagehide', 'beforeunload'].forEach(function (eventName) {
    global.addEventListener(eventName, function () { leaving = true; stop(); });
  });

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

  // ⚠ PLUS DE NETTOYAGE ICI (2026-10-18). Un `stripMarkdown` vivait à cette place, double de la
  // brique serveur `tts_text.text_for_speech` par laquelle passe de toute façon tout texte dit,
  // et il faisait PIRE : il EFFAÇAIT le code en ligne — « (`instant_preview`) » arrivait à la voix
  // en « () », d'où « les mots entre parenthèses ne sont pas lus » (Fabien). Le texte part tel
  // quel ; le serveur rend `spoken`, le texte effectivement dit, sur lequel se calent les lèvres.

  /** Une fin de phrase à `end` tombe-t-elle DANS un bloc de code (nombre impair de ``` avant) ?
   *  Couper là donnerait au serveur un bloc sans sa clôture, qu'il ne saurait plus annoncer. */
  function insideCodeBlock(text, end) {
    return (text.slice(0, end).match(/```/g) || []).length % 2 === 1;
  }

  /**
   * Le plus COURT groupe de phrases achevées qui atteint CHUNK_MIN_CHARS, retiré de `text` —
   * `{chunk, rest}`, `chunk` vide tant qu'aucun groupe n'est prêt.
   *
   * ⚠ JAMAIS « tout jusqu'à la dernière phrase achevée » (2026-10-13). Le découpage tenait à
   * une expression GOURMANDE : en flux, les jetons arrivent un par un et elle rendait bien des
   * groupes de ~70 caractères ; mais une réponse reçue D'UN BLOC (bouton « Écouter », tour
   * synchrone, fournisseur sans flux) partait entière en UN seul audio. Or l'avatar répartit
   * les mots sur la durée de chaque audio (`wama-avatar.js`) : sur 30 s, l'estimation dérive
   * et les lèvres décrochent de la voix. Mesuré : 4 phrases → 4 morceaux en flux, 1 d'un bloc.
   * Le découpage ne dépend plus du rythme d'arrivée du texte.
   */
  function takeSentences(text) {
    var boundary = /[.!?…](?=\s)/g, match;
    while ((match = boundary.exec(text))) {
      var end = match.index + 1;
      if (end >= CHUNK_MIN_CHARS && !insideCodeBlock(text, end)) {
        return { chunk: text.slice(0, end), rest: text.slice(end) };
      }
    }
    return { chunk: '', rest: text };
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
      // `spoken` : ce que le serveur a DIT après sa préparation (`tts_text`) — repli sur le
      // texte envoyé pour un serveur d'avant le 2026-10-18.
      return { blob: new Blob([bytes], { type: 'audio/wav' }), spoken: data.spoken || text };
    });
  }

  function avatarReady() {
    return !!(global.WamaAvatar && global.WamaAvatar.isReady && global.WamaAvatar.isReady());
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
    if (state.speaking) markSilent();
    setSpeaking(false);
  }

  /**
   * Ouvre UN tour de parole alimenté au fil de l'eau — c'est ce qui permet à l'assistant de
   * commencer à parler pendant qu'il écrit encore (flux, `WAMA_LLM §1bis` leviers 4+5).
   *
   * ⚠ POURQUOI CETTE API EXISTE : `speak()` RÉCLAME le canal à chaque appel (`Speech.claim()`),
   * donc l'appeler une fois par fragment reçu annulerait la phrase précédente à chaque fois.
   * Un flux a besoin d'UNE réclamation et d'une FILE.
   *
   * Rend `{push(texte), end()}` — `end()` rend une promesse résolue quand tout a été dit.
   * `options.force` : lire même en muet (geste explicite, bouton « Écouter »).
   */
  function speakStream(options) {
    if (!state.enabled && !(options && options.force)) {
      return { push: function () {}, end: function () { return Promise.resolve(false); } };
    }
    if (!global.WamaApp || !global.WamaApp.Speech) {
      return { push: function () {}, end: function () { return Promise.resolve(false); } };
    }
    var turn = global.WamaApp.Speech.claim();
    if (global.WamaAvatar && global.WamaAvatar.stop) global.WamaAvatar.stop();
    said.words = [];
    said.audibleUntil = Infinity;               // jusqu'à la fin de ce tour, `end()` la date
    setSpeaking(true);
    var pending = '';            // texte reçu, pas encore prononçable
    var playback = Promise.resolve();
    var ended = false;

    // Ne prend que des phrases ACHEVÉES (en flux, la dernière peut être coupée au milieu), par
    // groupes courts (`takeSentences`) ; la fin du tour vide ce qui reste, quoi qu'il arrive.
    function enqueueReady() {
      for (;;) {
        var taken = takeSentences(pending);
        if (!taken.chunk) return;
        pending = taken.rest;
        enqueue(taken.chunk);
      }
    }

    // ⚠ Un tour PÉRIMÉ n'a pas d'erreur à signaler : quitter la page ou relancer une question
    // pendant que l'assistant parle abandonne la requête en vol. Le navigateur rend alors
    // `AbortError` (notre propre annulation) ou `TypeError: Failed to fetch` (navigation), et
    // les journaliser remplissait la console de faux défauts — mesuré au smoke du 2026-09-26
    // en changeant de page pendant une vocalisation.
    function report(e) {
      if (!leaving && turn.valid() && e && e.name !== 'AbortError') {
        console.error('[WamaAssistantVoice]', e);
      }
    }

    // DEUX files, et c'est le point (2026-10-04) : les DEMANDES au service de voix partent
    // l'une après l'autre dès qu'une phrase est prête, sans attendre la LECTURE de la
    // précédente. Avant, une seule chaîne faisait « demander puis lire » : hors avatar, la
    // phrase suivante n'était demandée qu'une fois la précédente entièrement lue, d'où un
    // silence égal au temps de calcul entre deux phrases.
    var requests = Promise.resolve();

    function enqueue(text) {
      // La PHRASE prête part entière, jamais fragment par fragment : préparer chaque fragment
      // retirait son espace de tête, donc les mots arrivaient COLLÉS au service de voix
      // (« Bonjour » + « je » → « Bonjourje ») — et un marqueur coupé entre deux fragments
      // n'était jamais reconnu. La préparation elle-même est au serveur (`tts_text`).
      var sentence = String(text || '').trim();
      if (!sentence) return;
      // Les mots de l'ÉCHO : ceux de la phrase (le Markdown n'y laisse aucune lettre de plus).
      said.words = said.words.concat(speechWords(sentence));
      var audio = requests.then(function () {
        if (!turn.valid()) return null;
        return fetchSpeech(sentence, turn.signal);
      }).catch(function (e) { report(e); return null; });
      requests = audio;
      playback = playback.then(function () {
        return audio.then(function (speech) {
          if (!turn.valid() || !speech) return;
          return playChunk(speech.blob, speech.spoken, turn);
        });
      }).catch(report);
    }

    return {
      push: function (fragment) {
        if (ended) return;
        pending += (fragment || '');
        enqueueReady();
      },
      end: function () {
        if (ended) return playback;
        ended = true;
        var rest = pending;
        pending = '';
        if (rest) enqueue(rest);
        return playback.then(waitAvatarSilence).then(function () {
          if (turn.valid()) { markSilent(); setSpeaking(false); }
          return true;
        });
      },
    };
  }

  // `options.force` : lire même en muet — le bouton « Écouter » d'un message est un geste
  // explicite, pas une lecture automatique. Un texte ENTIER est le cas particulier d'un flux
  // qui reçoit tout d'un coup : une seule mécanique, donc un seul comportement à garder.
  function speak(text, options) {
    if (!String(text || '').trim()) return Promise.resolve(false);
    var stream = speakStream(options);
    stream.push(text);
    return stream.end();
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
    speakStream: speakStream,
    stop: stop,
    setEnabled: setEnabled,
    isEnabled: function () { return state.enabled; },
    isSpeaking: function () { return state.speaking; },
    isAudible: isAudible,
    isOwnSpeech: isOwnSpeech,
    bindButton: bindButton,
    onChange: function (fn) { listeners.push(fn); },
    takeSentences: takeSentences,
  };
})(window);
