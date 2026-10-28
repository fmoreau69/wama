/*
 * WamaAssistantListen — l'ÉCOUTE de l'assistant, brique commune (accueil + volet droit).
 * Pendant de `wama-assistant-voice.js` : celle-là le fait PARLER, celle-ci l'ENTEND.
 *
 * POURQUOI (2026-10-10, demande de Fabien : « une conversation naturelle avec l'assistant »,
 * « en brique commune utilisable dans l'assistant partout dans WAMA »). Jusque-là le micro de
 * l'accueil était une DICTÉE par la reconnaissance du navigateur (`webkitSpeechRecognition`) :
 *   • elle envoie l'audio à Google — contraire à « aucun traitement externe par défaut » ;
 *   • elle ne faisait que remplir la zone de saisie : il fallait envoyer, attendre, recliquer ;
 *   • elle n'existait que sur l'accueil.
 *
 * CE QUE FAIT LA BRIQUE.
 *   1. Capte le micro (getUserMedia, annulation d'écho du navigateur demandée), découpe la
 *      parole par l'ÉNERGIE du signal (début : la voix dépasse le bruit de fond ; fin : un
 *      silence qui dure), garde une avance de 400 ms pour ne pas couper la première syllabe.
 *   2. Transcrit : la phrase part en WAV 16 kHz à `/api/stt/`. LOCALEMENT par défaut (Whisper
 *      dans le service vocal, `tts_service.py`) — rien ne sort de WAMA ; chez Albert quand le
 *      profil autorise le cloud (`common/tts/speech_input.py`, 2026-10-11). Le serveur dit
 *      quel moteur a écouté (`engine`) et l'info-bulle de la dictée le répète.
 *   3. Deux gestes, deux boutons déclarés dans le chat :
 *        [data-assistant-mic]  DICTÉE — une phrase, écrite dans la zone de saisie (on relit,
 *                              on envoie soi-même) ;
 *        [data-assistant-talk] CONVERSATION — chaque phrase part toute seule, l'assistant
 *                              répond à voix haute, l'écoute continue. Reste actif d'une page
 *                              à l'autre pendant la session (sessionStorage).
 *   4. REPRENDRE LA PAROLE : pendant que l'assistant réfléchit ou parle, une voix nette et
 *      soutenue (seuils plus hauts) est écoutée ; une fois TRANSCRITE et reconnue comme n'étant
 *      pas sa propre voix (`isOwnSpeech`), elle coupe sa voix, interrompt son tour
 *      (`chat.abort()`) et devient la réplique suivante. Il parle donc encore le temps de la
 *      transcription (2026-10-13, décision de Fabien : l'annulation d'écho du navigateur peut
 *      ne pas couvrir ce que joue la page, un écho le coupait). ⚠ Seulement si le navigateur confirme
 *      l'annulation d'écho (`getSettings().echoCancellation`) : sans elle, l'assistant
 *      s'entendrait lui-même et s'interromprait. L'écoute est alors SOURDE pendant qu'il parle
 *      (chacun son tour), et le bouton le dit. Pendant qu'il RÉFLÉCHIT, rien ne joue : l'écoute
 *      reste ordinaire, et une phrase dite là remplace la question en cours (2026-10-27).
 *   5. ÉCOUTER SANS CHAT (2026-10-12, demande de Fabien : « appliquer les améliorations au
 *      bouton Speak, aligner sur le commun ») : `capture()` rend le même micro, le même
 *      découpage et la même route à une page qui veut seulement du TEXTE dit au micro — le
 *      port « en direct » du transcriber, qui passait encore par la reconnaissance du
 *      navigateur (Google). Les phrases arrivent dans l'ordre de la parole ; `record: true`
 *      garde en plus l'enregistrement complet, pris sur le MÊME flux.
 *
 * CONTRAT.
 *   mount()                : câble les boutons de chaque `[data-wama-chat]` (automatique).
 *   configure({sttUrl, turnUrl}) : route de transcription (défaut : `data-stt-url` du chat,
 *                            sinon `/api/stt/`) et de l'avis de fin de tour (`data-turn-url`,
 *                            sinon `/api/end-of-turn/`).
 *   capture(opts)          : Promise<{stop()}> — écoute continue hors chat. `opts` :
 *                            onText(phrase, engine), onPhase('listening'|'hearing'|
 *                            'transcribing'|'idle'), onError(message), record (bool),
 *                            onEnd({text, language, engine, recording}) — appelé une fois, que
 *                            l'arrêt vienne de `stop()` ou d'une autre écoute qui prend le micro.
 *                            Rejette avec le message lisible si le micro ne s'ouvre pas.
 *   stop()                 : coupe tout (micro rendu, conversation arrêtée).
 *   state()                : {mode: 'off'|'dictation'|'conversation'|'capture', phase, echoCancelled}.
 *
 * Dépend de : `WamaCapture` (accès au micro, enregistrement — 2026-10-26), `WamaAssistantChat`
 * (send/abort/isBusy/input), `WamaAssistantVoice` (isAudible/isOwnSpeech/stop/onChange),
 * `WamaApp.toast` et `WamaApp.csrfToken` si présents.
 *
 * L'ÉCHO (2026-10-13) : la fin d'une réponse, encore jouée par le haut-parleur, est repartie
 * comme réplique — l'assistant s'est répondu à lui-même. Trois gestes, dans la brique : l'écoute
 * tient l'assistant pour actif tant que sa voix est AUDIBLE (latence de sortie comprise) ; quand
 * il se tait, l'avance du découpage, faite de sa voix, est oubliée ; et une phrase commencée
 * pendant qu'il s'entendait, faite de ses propres mots, est écartée (`isOwnSpeech`).
 */
(function (global) {
  'use strict';

  var TARGET_RATE = 16000;               // ce qu'attend Whisper ; on rééchantillonne ici
  var SESSION_KEY = 'wama.assistant.talk';

  //: Seuils du découpage, en dB AU-DESSUS du bruit de fond mesuré (et en ms). Deux jeux :
  //: `normal` quand l'assistant se tait, `interrupt` quand il réfléchit ou parle — il faut
  //: alors une voix plus forte et plus longue pour lui couper la parole.
  var PARAMS = {
    normal:    { startDb: 10, floorDb: -55, startMs: 120 },
    interrupt: { startDb: 18, floorDb: -42, startMs: 350 },
  };
  var KEEP_DB = 6;                        // au-dessus : la parole continue
  var END_MS = { conversation: 900, dictation: 1300, capture: 900 };
  var MIN_SPEECH_MS = 250;                // en dessous : un bruit, pas une phrase
  var MAX_UTTERANCE_MS = 30000;
  var PREROLL_MS = 400;
  //: Le bruit de fond = le niveau le plus BAS entendu sur cette fenêtre (2026-10-27). Il se
  //: mesurait sur les seules trames jugées calmes — or « calme » se jugeait par rapport à lui :
  //: une pièce au-dessus de -55 dBFS (souffle d'un casque, gain automatique) n'était jamais
  //: apprise. Mesuré sur la brique servie : la « phrase » s'ouvrait à 85 ms et ne se fermait
  //: plus, jusqu'au plafond de 30 s — le bouton pulsait, aucun texte ne venait.
  var FLOOR_WINDOW_MS = 4000;
  var DIGITAL_SILENCE_DB = -100;          // trames nulles d'un périphérique qui s'ouvre : pas un fond
  //: FIN DE TOUR (2026-10-28) : après une pause courte, la conversation demande au serveur si
  //: la phrase est FINIE (Smart Turn, `common/tts/end_of_turn.py`). « Finie » → elle part sans
  //: attendre `END_MS` ; « pas finie » → la pause peut durer `patientMs` ; pas d'avis (modèle
  //: absent, service muet, réponse tardive) → `END_MS`, exactement comme avant. Le silence garde
  //: ses bornes : l'avis ne fait que déplacer la décision entre elles.
  //: `keepSeconds` n'allège que l'envoi : la fenêtre du modèle est celle du service
  //: (`tts_service.TURN_SECONDS`), qui tronque de toute façon.
  var TURN = { askAfterMs: 300, patientMs: 2000, keepSeconds: 8 };

  var cfg = { sttUrl: '', turnUrl: '' };
  var ctl = null;                         // le contrôleur ACTIF (un seul micro par page)

  function csrfToken() {
    if (global.WamaApp && global.WamaApp.csrfToken) return global.WamaApp.csrfToken();
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  function say(message, type) {
    if (global.WamaApp && global.WamaApp.toast) global.WamaApp.toast(message, type || 'warning');
    else console.warn('[WamaAssistantListen]', message);
  }

  function remember(on) {
    try {
      if (on) global.sessionStorage.setItem(SESSION_KEY, '1');
      else global.sessionStorage.removeItem(SESSION_KEY);
    } catch (_) {}
  }

  function remembered() {
    try { return global.sessionStorage.getItem(SESSION_KEY) === '1'; } catch (_) { return false; }
  }

  // ── Signal ───────────────────────────────────────────────────────────────────
  function levelDb(frame) {
    var sum = 0;
    for (var i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
    var rms = Math.sqrt(sum / (frame.length || 1));
    return rms > 1e-9 ? 20 * Math.log10(rms) : -120;
  }

  // Moyenne par paquets : suffisant pour la parole (≤ 8 kHz utiles), et sans dépendance.
  function downsample(samples, rate) {
    if (rate === TARGET_RATE) return samples;
    var ratio = rate / TARGET_RATE;
    var out = new Float32Array(Math.floor(samples.length / ratio));
    for (var i = 0; i < out.length; i++) {
      var start = Math.floor(i * ratio), end = Math.min(samples.length, Math.floor((i + 1) * ratio));
      var sum = 0;
      for (var j = start; j < end; j++) sum += samples[j];
      out[i] = sum / Math.max(1, end - start);
    }
    return out;
  }

  function toWav(samples) { return new Blob([wavBytes(samples)], { type: 'audio/wav' }); }

  // WAV PCM 16 bits mono à 16 kHz — l'en-tête de 44 octets, puis les échantillons.
  function wavBytes(samples) {
    var buffer = new ArrayBuffer(44 + samples.length * 2);
    var view = new DataView(buffer);
    function text(offset, s) { for (var i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i)); }
    text(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); text(8, 'WAVE');
    text(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
    view.setUint16(22, 1, true); view.setUint32(24, TARGET_RATE, true);
    view.setUint32(28, TARGET_RATE * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    text(36, 'data'); view.setUint32(40, samples.length * 2, true);
    for (var i = 0; i < samples.length; i++) {
      var s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return buffer;
  }

  function concat(frames) {
    var n = 0;
    frames.forEach(function (f) { n += f.length; });
    var out = new Float32Array(n), at = 0;
    frames.forEach(function (f) { out.set(f, at); at += f.length; });
    return out;
  }

  /**
   * Découpe un flux de trames en PHRASES. `onEvent('start')` quand une voix commence,
   * `onEvent('end', samples)` quand elle s'arrête (avance comprise), `onEvent('discard')`
   * pour un bruit trop court. `mode(frame)` rend 'normal', 'interrupt' ou 'deaf'.
   * `judge(samples)` (facultatif) : Promise<{complete: true|false|null}> — l'avis de fin de tour
   * demandé après `TURN.askAfterMs` de pause, une fois par pause.
   */
  function Segmenter(rate, endMs, onEvent, judge) {
    this.rate = rate;
    this.endMs = endMs;
    this.onEvent = onEvent;
    this.judge = judge || null;
    this.floor = null;                    // bruit de fond : le plus bas de `levels`, borné
    this.levels = [];                     // [dB, ms] des dernières trames (FLOOR_WINDOW_MS)
    this.levelsMs = 0;
    this.reset();
  }

  /** Retient le niveau d'une trame et en déduit le fond : le minimum de la fenêtre. Un bruit
   *  constant devient le fond même s'il est fort ; une voix, qui a ses creux, ne le devient pas. */
  Segmenter.prototype.track = function (db, ms) {
    if (db <= DIGITAL_SILENCE_DB) return;
    this.levels.push([db, ms]);
    this.levelsMs += ms;
    while (this.levelsMs > FLOOR_WINDOW_MS && this.levels.length > 1) {
      this.levelsMs -= this.levels.shift()[1];
    }
    var low = Infinity;
    for (var i = 0; i < this.levels.length; i++) low = Math.min(low, this.levels[i][0]);
    this.floor = Math.min(-30, Math.max(-90, low));
  };

  Segmenter.prototype.reset = function () {
    this.preroll = [];
    this.prerollMs = 0;
    this.frames = null;
    this.loudMs = 0;
    this.quietMs = 0;
    this.speechMs = 0;
    this.totalMs = 0;
    this.pause = 0;                       // numéro de la pause en cours (l'avis lui est propre)
    this.asked = false;                   // avis déjà demandé pour cette pause
    this.patient = false;                 // « pas finie » : la pause peut durer `TURN.patientMs`
  };

  Segmenter.prototype.feed = function (frame, mode) {
    var db = levelDb(frame);
    var ms = frame.length / this.rate * 1000;
    if (mode === 'deaf') { this.reset(); return; }
    this.track(db, ms);
    if (this.floor === null) return;      // rien encore que du silence numérique
    var p = PARAMS[mode] || PARAMS.normal;

    if (!this.frames) {
      this.preroll.push(frame);
      this.prerollMs += ms;
      while (this.prerollMs > PREROLL_MS && this.preroll.length > 1) {
        this.prerollMs -= this.preroll.shift().length / this.rate * 1000;
      }
      if (db > Math.max(this.floor + p.startDb, p.floorDb)) this.loudMs += ms;
      else this.loudMs = 0;
      if (this.loudMs >= p.startMs) {
        this.frames = this.preroll;
        this.preroll = [];
        this.prerollMs = 0;
        this.speechMs = this.loudMs;
        this.totalMs = this.loudMs;
        this.quietMs = 0;
        this.onEvent('start', null, mode);
      }
      return;
    }

    this.frames.push(frame);
    this.totalMs += ms;
    if (db > this.floor + KEEP_DB) {
      if (this.quietMs > 0) { this.pause++; this.asked = false; this.patient = false; }
      this.quietMs = 0;
      this.speechMs += ms;
    } else this.quietMs += ms;
    if (this.judge && !this.asked && this.quietMs >= TURN.askAfterMs && this.speechMs >= MIN_SPEECH_MS) {
      this.asked = true;
      this.askJudge();
    }
    var endMs = this.patient ? TURN.patientMs : this.endMs;
    if (this.quietMs >= endMs || this.totalMs >= MAX_UTTERANCE_MS) this.finish();
  };

  /** L'avis de fin de tour sur la phrase dite jusqu'ici. Il ne vaut que pour SA pause : si la
   *  voix a repris, ou si la phrase est déjà partie, il arrive trop tard et ne change rien. */
  Segmenter.prototype.askJudge = function () {
    var self = this, frames = this.frames, pause = this.pause;
    Promise.resolve().then(function () { return self.judge(concat(frames)); }).then(function (verdict) {
      if (self.frames !== frames || self.pause !== pause || !verdict) return;
      if (verdict.complete === true) self.finish();
      else if (verdict.complete === false) self.patient = true;
    }).catch(function () {});
  };

  /** Oublie l'AVANCE (et le début de voix en cours de mesure) — sans toucher une phrase ouverte. */
  Segmenter.prototype.forgetPreroll = function () {
    if (this.frames) return;
    this.preroll = [];
    this.prerollMs = 0;
    this.loudMs = 0;
  };

  Segmenter.prototype.finish = function () {
    if (!this.frames) return;
    var frames = this.frames, speechMs = this.speechMs;
    this.reset();
    if (speechMs < MIN_SPEECH_MS) { this.onEvent('discard'); return; }
    this.onEvent('end', concat(frames));
  };

  // ── Micro ────────────────────────────────────────────────────────────────────
  // Un AudioWorklet transmet le signal BRUT par paquets de 2048 échantillons (~43 ms à 48 kHz).
  // Le module est écrit ici et chargé par une URL de Blob : aucun fichier de plus à servir.
  var TAP_SOURCE = [
    'class WamaTap extends AudioWorkletProcessor {',
    '  constructor() { super(); this.buf = new Float32Array(2048); this.n = 0; }',
    '  process(inputs) {',
    '    var ch = inputs[0] && inputs[0][0];',
    '    if (ch) for (var i = 0; i < ch.length; i++) {',
    '      this.buf[this.n++] = ch[i];',
    '      if (this.n === this.buf.length) { this.port.postMessage(this.buf.slice(0)); this.n = 0; }',
    '    }',
    '    return true;',
    '  }',
    '}',
    "registerProcessor('wama-tap', WamaTap);",
  ].join('\n');

  // L'accès au micro (contexte sécurisé, refus expliqué, pistes rendues) : brique `WamaCapture`.
  function openMic(onFrame) {
    var mic = { stream: null, ctx: null, node: null };
    return global.WamaCapture.open({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    }).then(function (stream) {
      mic.stream = stream;
      var Ctx = global.AudioContext || global.webkitAudioContext;
      mic.ctx = new Ctx();
      var url = URL.createObjectURL(new Blob([TAP_SOURCE], { type: 'application/javascript' }));
      return mic.ctx.audioWorklet.addModule(url).then(function () {
        URL.revokeObjectURL(url);
        var source = mic.ctx.createMediaStreamSource(stream);
        mic.node = new AudioWorkletNode(mic.ctx, 'wama-tap');
        mic.node.port.onmessage = function (e) { onFrame(e.data); };
        // Relié à la sortie par un gain NUL : un nœud hors du graphe n'est pas tiré.
        var mute = mic.ctx.createGain();
        mute.gain.value = 0;
        source.connect(mic.node);
        mic.node.connect(mute);
        mute.connect(mic.ctx.destination);
        mic.echoCancelled = global.WamaCapture.trackSettings(stream, 'microphone').echoCancellation === true;
        // Le micro que le NAVIGATEUR a ouvert, dit dans l'info-bulle : ce n'est pas toujours
        // celui où l'on parle (périphérique par défaut du système, casque branché après coup).
        mic.label = global.WamaCapture.trackLabel(stream, 'microphone');
        mic.rate = mic.ctx.sampleRate;
        return mic;
      });
    }).catch(function (e) { closeMic(mic); throw e; });
  }

  function closeMic(mic) {
    if (!mic) return;
    if (mic.node) { try { mic.node.port.onmessage = null; mic.node.disconnect(); } catch (_) {} }
    global.WamaCapture.close(mic.stream);
    if (mic.ctx) { try { mic.ctx.close(); } catch (_) {} }
  }

  // Un refus d'accès arrive déjà expliqué ; une panne du traitement audio (module de découpage)
  // reçoit le même message de repli « Micro indisponible : … ».
  function explainMicError(e) { return global.WamaCapture.explain(e, 'microphone'); }

  // UN envoi de WAV au serveur, le même pour la transcription, le préchauffage et la fin de tour.
  function postWav(url, wav) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'audio/wav', 'X-CSRFToken': csrfToken() },
      body: wav,
    });
  }

  // La réponse ENTIÈRE du serveur ({text, language, engine}) ; `transcribe` n'en garde que le texte.
  function transcribeClip(samples, rate) {
    return postWav(cfg.sttUrl || '/api/stt/', toWav(downsample(samples, rate))).then(function (r) {
      return r.json().catch(function () { return { error: 'réponse illisible (' + r.status + ')' }; });
    }).then(function (data) {
      if (data.error) throw new Error(data.error);
      if (data.engine) heardBy = data.engine;
      return data;
    });
  }

  function transcribe(samples, rate) {
    return transcribeClip(samples, rate).then(function (data) { return (data.text || '').trim(); });
  }

  // L'avis de fin de tour : les `TURN.keepSeconds` dernières secondes, en WAV 16 kHz. Le serveur
  // qui répond `available: false` (aucun modèle installé) ou 404 (route pas encore servie : la
  // brique est relue à chaud, les routes au redémarrage) n'est plus interrogé de la page.
  var turnAvailable = true;
  function judgeTurn(samples, rate) {
    if (!turnAvailable) return Promise.resolve(null);
    var keep = Math.floor(TURN.keepSeconds * rate);
    var tail = samples.length > keep ? samples.subarray(samples.length - keep) : samples;
    return postWav(cfg.turnUrl || '/api/end-of-turn/', toWav(downsample(tail, rate))).then(function (r) {
      if (r.status === 404) turnAvailable = false;
      return r.ok ? r.json() : null;
    }).then(function (data) {
      if (data && data.available === false) turnAvailable = false;
      return data;
    }).catch(function () { return null; });
  }

  // Le moteur qui a écouté la dernière fois, dit par le serveur ('' tant qu'il n'a rien dit).
  var heardBy = '';
  function listenerLabel() {
    if (!heardBy || heardBy === 'local') return 'transcription locale, rien ne sort de WAMA';
    return 'transcription par ' + heardBy.split(':')[0] + ', autorisé par votre profil';
  }

  // PRÉCHAUFFAGE : le premier appel charge Whisper dans le service (37 à 50 s mesurés). On le
  // déclenche dès que l'écoute s'ouvre, avec un quart de seconde de silence — le filtre de
  // parole le réduit à rien —, pour que la première vraie phrase ne paie pas ce chargement.
  // `warmup=1` : quand le profil écoute par un modèle DISTANT, le serveur n'envoie rien.
  var warmedAt = 0;
  function warmUp() {
    if (Date.now() - warmedAt < 5 * 60 * 1000) return;
    warmedAt = Date.now();
    var url = cfg.sttUrl || '/api/stt/';
    postWav(url + (url.indexOf('?') < 0 ? '?' : '&') + 'warmup=1', toWav(new Float32Array(TARGET_RATE / 4)))
      .then(function (r) { return r.json(); })
      .then(function (data) { if (data && data.engine) heardBy = data.engine; })
      .catch(function () {});
    // Le juge de fin de tour se charge aussi d'avance (~35 s à froid) : son premier avis
    // arriverait sinon après la pause, donc pour rien.
    judgeTurn(new Float32Array(TARGET_RATE / 4), TARGET_RATE);
  }

  // ── Contrôleur : un chat, ses deux boutons ───────────────────────────────────
  function Controller(chat, root) {
    this.chat = chat;
    this.root = root;
    this.micBtn = root.querySelector('[data-assistant-mic]');
    this.talkBtn = root.querySelector('[data-assistant-talk]');
    this.mode = 'off';                    // off | dictation | conversation
    this.phase = 'idle';                  // idle | listening | hearing | transcribing
    this.mic = null;
    this.segmenter = null;
    this.lastTurn = Promise.resolve();
    this.pending = 0;                     // transcriptions en vol
    this.bind();
    this.render();
  }

  Controller.prototype.bind = function () {
    var self = this;
    if (this.micBtn) this.micBtn.addEventListener('click', function () { self.toggleDictation(); });
    if (this.talkBtn) this.talkBtn.addEventListener('click', function () { self.toggleConversation(); });
    if (global.WamaAssistantVoice && global.WamaAssistantVoice.onChange) {
      global.WamaAssistantVoice.onChange(function () { self.render(); });
    }
  };

  /** L'assistant est-il en train de répondre (réflexion OU voix) ? « Voix » = AUDIBLE : le
   *  haut-parleur joue encore après la fin de l'audio (latence de sortie, 2026-10-13). */
  Controller.prototype.assistantActive = function () {
    var voice = global.WamaAssistantVoice;
    return !!((this.chat.isBusy && this.chat.isBusy()) || (voice && voice.isAudible()));
  };

  /** Pendant qu'il RÉFLÉCHIT, rien ne sort du haut-parleur : aucune écoute ne s'y assourdit ni
   *  ne s'y durcit (2026-10-27, décision de Fabien). Seule sa voix AUDIBLE le fait. */
  Controller.prototype.frameMode = function () {
    if (this.phase === 'transcribing' && this.mode === 'dictation') return 'deaf';
    var voice = global.WamaAssistantVoice;
    if (this.mode !== 'conversation' || !(voice && voice.isAudible())) return 'normal';
    return (this.mic && this.mic.echoCancelled) ? 'interrupt' : 'deaf';
  };

  Controller.prototype.start = function (mode) {
    var self = this;
    if (ctl && ctl !== this) ctl.stop();
    ctl = this;
    this.mode = mode;
    this.phase = 'listening';
    this.render();
    warmUp();
    return openMic(function (frame) { self.onFrame(frame); }).then(function (mic) {
      if (self.mode !== mode) { closeMic(mic); return; }    // arrêté pendant l'ouverture
      self.mic = mic;
      // La fin de tour ne s'arbitre qu'en CONVERSATION : une dictée se relit avant l'envoi, et
      // `capture()` transcrit au fil de la parole sans tour à rendre.
      self.segmenter = new Segmenter(mic.rate, END_MS[mode], function (evt, samples, how) {
        self.onSegment(evt, samples, how);
      }, mode === 'conversation' ? function (samples) { return judgeTurn(samples, mic.rate); } : null);
      // Contexte audio créé hors d'un geste (reprise d'une conversation au changement de page) :
      // le navigateur le laisse suspendu jusqu'au premier clic ou à la première touche.
      if (mic.ctx.state === 'suspended') {
        var resume = function () {
          document.removeEventListener('pointerdown', resume, true);
          document.removeEventListener('keydown', resume, true);
          if (self.mic === mic) mic.ctx.resume().then(function () { self.render(); });
        };
        document.addEventListener('pointerdown', resume, true);
        document.addEventListener('keydown', resume, true);
      }
      self.render();
    }).catch(function (e) {
      self.mode = 'off';
      self.phase = 'idle';
      if (ctl === self) ctl = null;
      remember(false);
      self.render();
      say(explainMicError(e));
    });
  };

  Controller.prototype.stop = function () {
    closeMic(this.mic);
    this.mic = null;
    this.segmenter = null;
    this.mode = 'off';
    this.phase = 'idle';
    if (ctl === this) ctl = null;
    this.render();
  };

  Controller.prototype.toggleDictation = function () {
    if (this.mode === 'conversation') return;             // le bouton est grisé dans ce cas
    if (this.mode === 'dictation') {
      // Second clic : « j'ai fini » — la phrase en cours part tout de suite, sinon on arrête.
      if (this.phase === 'hearing' && this.segmenter) this.segmenter.finish();
      else this.stop();
      return;
    }
    this.start('dictation');
  };

  Controller.prototype.toggleConversation = function () {
    if (this.mode === 'conversation') { remember(false); this.stop(); return; }
    remember(true);
    this.start('conversation');
  };

  Controller.prototype.onFrame = function (frame) {
    if (!this.segmenter) return;
    var mode = this.frameMode();
    // L'assistant vient de se taire : ce que le micro a gardé en AVANCE, c'est sa voix — pas le
    // début de la phrase suivante (2026-10-13 : la fin d'une réponse repartait comme réplique).
    if (mode === 'normal' && this.lastFrameMode !== 'normal') this.segmenter.forgetPreroll();
    this.lastFrameMode = mode;
    this.segmenter.feed(frame, mode);
  };

  Controller.prototype.onSegment = function (evt, samples, how) {
    var self = this;
    if (evt === 'start') {
      // Quand le SON a commencé (le découpage l'a mesuré avant de déclarer la phrase) : c'est
      // ce qui dit, à la fin, si la voix de l'assistant s'entendait encore (`isOwnSpeech`).
      this.heardAt = Date.now() - (this.segmenter ? this.segmenter.speechMs : 0);
      // Une voix qui couvre l'assistant : on ne le coupe qu'une fois la phrase transcrite et
      // reconnue comme n'étant pas la sienne (2026-10-13, décision de Fabien) — l'annulation
      // d'écho du navigateur peut ne pas couvrir ce que joue la page. Une phrase commencée
      // pendant qu'il réfléchit le reprend aussi : elle remplace la question en cours.
      this.bargeIn = (how === 'interrupt') || (this.mode === 'conversation' && this.assistantActive());
      this.phase = 'hearing';
      this.render();
      return;
    }
    if (evt === 'discard') { this.phase = 'listening'; this.render(); return; }

    // 'end' : une phrase complète.
    var mode = this.mode, rate = this.mic ? this.mic.rate : TARGET_RATE, heardAt = this.heardAt;
    var bargeIn = this.bargeIn;
    this.bargeIn = false;
    if (mode === 'dictation') { closeMic(this.mic); this.mic = null; this.segmenter = null; }
    this.phase = 'transcribing';
    this.pending++;
    this.render();
    transcribe(samples, rate).then(function (text) {
      // L'assistant ne se répond jamais à lui-même : sa propre voix, entendue au micro, n'est
      // ni une réplique ni une dictée (`WamaAssistantVoice.isOwnSpeech`).
      var voice = global.WamaAssistantVoice;
      if (text && voice && voice.isOwnSpeech(text, heardAt)) return;
      if (mode === 'dictation') { self.writeDraft(text); return; }
      if (!text || self.mode !== 'conversation') return;
      if (bargeIn) self.interrupt();
      self.sendTurn(text);
    }).catch(function (e) {
      say(e.message || String(e));
    }).then(function () {
      self.pending = Math.max(0, self.pending - 1);
      if (mode === 'dictation') { self.mode = 'off'; self.phase = 'idle'; if (ctl === self) ctl = null; }
      else if (self.mode === 'conversation' && self.phase === 'transcribing') self.phase = 'listening';
      self.render();
    });
  };

  /** Reprendre la parole : la voix se tait, le tour en cours s'interrompt. */
  Controller.prototype.interrupt = function () {
    if (global.WamaAssistantVoice) global.WamaAssistantVoice.stop();
    if (this.chat.abort) this.chat.abort();
  };

  Controller.prototype.writeDraft = function (text) {
    if (!text) { say('Je n’ai rien compris — réessayez en parlant plus près du micro.', 'info'); return; }
    var input = this.chat.input;
    input.value = input.value.trim() ? input.value.trim() + ' ' + text : text;
    input.dispatchEvent(new Event('input'));               // la brique de chat ajuste sa hauteur
    input.focus();
  };

  // Les répliques partent dans l'ordre où elles ont été dites : chacune attend la précédente
  // (un tour en cours, lui, est repris par `send()` même — la saisie reste ouverte, 27/10).
  Controller.prototype.sendTurn = function (text) {
    var self = this;
    this.lastTurn = this.lastTurn.then(function () {
      if (self.mode !== 'conversation') return;
      self.chat.input.value = text;
      return self.chat.send();
    }).catch(function () {}).then(function () { self.render(); });
  };

  // ── Rendu des boutons ────────────────────────────────────────────────────────
  function paint(btn, icon, cls, title, pulse) {
    if (!btn) return;
    var i = btn.querySelector('i') || btn;
    i.className = 'fas ' + icon;
    ['btn-outline-secondary', 'btn-success', 'btn-danger', 'btn-outline-success']
      .forEach(function (c) { btn.classList.toggle(c, c === cls); });
    btn.classList.toggle('wama-listen-pulse', !!pulse);
    btn.title = title;
  }

  Controller.prototype.render = function () {
    var phase = this.phase, mode = this.mode;
    var suspended = !!(this.mic && this.mic.ctx && this.mic.ctx.state === 'suspended');
    // Dictée
    if (mode === 'dictation') {
      if (phase === 'transcribing') paint(this.micBtn, 'fa-circle-notch fa-spin', 'btn-danger', 'Transcription…');
      else paint(this.micBtn, 'fa-microphone', 'btn-danger', 'J’écoute — cliquez quand vous avez fini', phase === 'hearing');
    } else {
      paint(this.micBtn, 'fa-microphone', 'btn-outline-secondary',
            'Dicter un message (' + listenerLabel() + ')');
    }
    if (this.micBtn) this.micBtn.disabled = mode === 'conversation';
    // Conversation
    if (mode !== 'conversation') {
      paint(this.talkBtn, 'fa-headset', 'btn-outline-secondary',
            'Conversation vocale : parlez, l’assistant répond à voix haute');
      return;
    }
    if (suspended) {
      paint(this.talkBtn, 'fa-headset', 'btn-outline-success', 'Conversation en pause — cliquez dans la page pour reprendre l’écoute');
    } else if (phase === 'hearing') {
      paint(this.talkBtn, 'fa-headset', 'btn-danger', 'Je vous écoute…', true);
    } else if (phase === 'transcribing') {
      paint(this.talkBtn, 'fa-circle-notch fa-spin', 'btn-success', 'Transcription…');
    } else if (this.assistantActive()) {
      paint(this.talkBtn, 'fa-headset', 'btn-outline-success',
            (this.frameMode() !== 'deaf')
              ? 'L’assistant répond — parlez pour l’interrompre (clic : arrêter la conversation)'
              : 'L’assistant répond — l’écoute reprend quand il a fini (clic : arrêter la conversation)');
    } else {
      paint(this.talkBtn, 'fa-headset', 'btn-success', 'À vous — je vous écoute'
            + (this.mic && this.mic.label ? ' (micro : ' + this.mic.label + ')' : '')
            + ' (clic : arrêter la conversation)');
    }
  };

  // ── Écoute sans chat : `capture()` ───────────────────────────────────────────
  // Même micro, même découpage, même route que le chat. Les transcriptions partent UNE PAR UNE :
  // le texte arrive dans l'ordre de la parole, et un profil qui écoute chez Albert ne lui envoie
  // pas une rafale (limite de débit — au-delà, `speech_input` rend la phrase au local).
  function Capture(opts) {
    this.opts = opts || {};
    this.mode = 'capture';
    this.phase = 'idle';
    this.mic = null;
    this.segmenter = null;
    this.recorder = null;                 // `WamaCapture.record` quand `record: true`
    this.texts = [];
    this.language = '';
    this.pending = 0;
    this.queue = Promise.resolve();
    this.ended = null;                    // la promesse de fin, une seule même si stop() est rappelé
  }

  Capture.prototype.setPhase = function (phase) {
    this.phase = phase;
    if (this.opts.onPhase) { try { this.opts.onPhase(phase); } catch (_) {} }
  };

  Capture.prototype.start = function () {
    var self = this;
    if (ctl && ctl !== this) {
      if (ctl.mode === 'conversation') remember(false);   // elle ne reprendra pas à la page suivante
      ctl.stop();
    }
    ctl = this;
    warmUp();
    return openMic(function (frame) {
      if (self.segmenter) self.segmenter.feed(frame, 'normal');
    }).then(function (mic) {
      if (self.mode !== 'capture') { closeMic(mic); return self; }   // arrêté pendant l'ouverture
      self.mic = mic;
      self.segmenter = new Segmenter(mic.rate, END_MS.capture, function (evt, samples) {
        self.onSegment(evt, samples);
      });
      // Sans enregistreur dans ce navigateur, le texte reste, sans enregistrement.
      if (self.opts.record) self.recorder = global.WamaCapture.record(mic.stream);
      self.setPhase('listening');
      return self;
    }).catch(function (e) {
      self.mode = 'off';
      if (ctl === self) ctl = null;
      self.setPhase('idle');
      throw new Error(explainMicError(e));
    });
  };

  Capture.prototype.onSegment = function (evt, samples) {
    var self = this;
    if (evt === 'start') { this.setPhase('hearing'); return; }
    if (evt === 'discard') { this.setPhase('listening'); return; }
    var rate = this.mic ? this.mic.rate : TARGET_RATE;
    this.pending++;
    this.setPhase('transcribing');
    this.queue = this.queue.then(function () {
      return transcribeClip(samples, rate);
    }).then(function (data) {
      var text = (data.text || '').trim();
      if (data.language) self.language = data.language;
      if (!text) return;
      self.texts.push(text);
      if (self.opts.onText) self.opts.onText(text, heardBy);
    }).catch(function (e) {
      var message = (e && e.message) || String(e);
      if (self.opts.onError) self.opts.onError(message); else say(message);
    }).then(function () {
      self.pending = Math.max(0, self.pending - 1);
      if (self.mode === 'capture' && !self.pending && self.phase === 'transcribing') self.setPhase('listening');
    });
  };

  /** Arrête l'écoute ; la phrase en cours part encore. Rend (et passe à `onEnd`) le résultat. */
  Capture.prototype.stop = function () {
    if (this.ended) return this.ended;
    var self = this;
    if (this.segmenter) this.segmenter.finish();
    this.mode = 'off';
    if (ctl === this) ctl = null;
    var recorded = this.recorder ? this.recorder.stop() : Promise.resolve(null);
    this.ended = recorded.then(function (recording) {
      closeMic(self.mic);
      self.mic = null;
      self.segmenter = null;
      return self.queue.then(function () {
        var result = { text: self.texts.join('\n'), language: self.language,
                       engine: heardBy, recording: recording };
        self.setPhase('idle');
        if (self.opts.onEnd) self.opts.onEnd(result);
        return result;
      });
    });
    return this.ended;
  };

  function capture(opts) { return new Capture(opts).start(); }

  // ── Montage ──────────────────────────────────────────────────────────────────
  var controllers = [];

  function mount() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-wama-chat]'), function (root) {
      if (root._wamaListen || !root._wamaChat) return;
      if (!root.querySelector('[data-assistant-mic], [data-assistant-talk]')) return;
      if (!cfg.sttUrl && root.dataset.sttUrl) cfg.sttUrl = root.dataset.sttUrl;
      if (!cfg.turnUrl && root.dataset.turnUrl) cfg.turnUrl = root.dataset.turnUrl;
      root._wamaListen = new Controller(root._wamaChat, root);
      controllers.push(root._wamaListen);
    });
    // Conversation ouverte sur la page précédente : elle reprend, si le micro est déjà permis
    // (sinon on n'ouvre pas de demande d'autorisation sans geste de l'utilisateur).
    var first = controllers.filter(function (c) { return c.talkBtn; })[0];
    if (first && remembered()) {
      global.WamaCapture.permission('microphone').then(function (state) {
        if (state === 'granted' && first.mode === 'off') first.start('conversation');
      });
    }
  }

  global.addEventListener('pagehide', function () { if (ctl) { closeMic(ctl.mic); ctl.mic = null; } });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();

  global.WamaAssistantListen = {
    mount: mount,
    configure: function (opts) {
      if (opts && opts.sttUrl) cfg.sttUrl = opts.sttUrl;
      if (opts && opts.turnUrl) cfg.turnUrl = opts.turnUrl;
    },
    capture: capture,
    stop: function () { remember(false); if (ctl) ctl.stop(); },
    state: function () {
      return ctl ? { mode: ctl.mode, phase: ctl.phase, echoCancelled: !!(ctl.mic && ctl.mic.echoCancelled) }
                 : { mode: 'off', phase: 'idle', echoCancelled: false };
    },
    // Exposés pour les tests (découpage, encodage, enchaînement — sans micro ni DOM réel).
    _Controller: Controller,
    _Capture: Capture,
    _Segmenter: Segmenter,
    _downsample: downsample,
    _wavBytes: wavBytes,
    _warmUp: warmUp,
    _judgeTurn: judgeTurn,
    _TURN: TURN,
    _listenerLabel: listenerLabel,
  };
})(window);
