/**
 * WamaAvatar — avatar 3D parlant branché sur le canal de parole commun.
 *
 * POURQUOI CE MODULE. L'assistant disposait déjà de toute la chaîne (STT navigateur → LLM local
 * à outils → TTS Kokoro → `WamaApp.Speech`) : le SEUL maillon manquant était le rendu. Ce module
 * ne refait donc aucun de ces maillons — il se greffe sur l'audio que `Speech` allait jouer.
 *
 * RENDU 100 % NAVIGATEUR (three.js/TalkingHead) : zéro VRAM serveur, aucun conflit avec les
 * files Celery ni le gouverneur de ressources. C'est ce qui distingue cette voie de LiveTalking
 * (photoréaliste, mais une session = un GPU mobilisé).
 *
 * ⚠ MODULE ES6 : à charger en `<script type="module">`, APRÈS l'importmap commune
 * (`common/_three_importmap.html`), qui résout `three`, `three/addons/` et `talkinghead` vers
 * `vendors/`. Sans elle, le navigateur ne sait pas résoudre ces noms et rien ne se charge.
 */
import { TalkingHead } from 'talkinghead';

/** Langues ayant un module de visèmes (lipsync-<lang>.mjs vendorisé). Les autres retombent
 *  sur l'anglais : mieux vaut un lip-sync approximatif qu'un `import()` dynamique en échec. */
const VISEME_LANGUAGES = ['fr', 'en', 'de', 'fi', 'lt'];

let head = null;          // instance TalkingHead
let ready = false;        // avatar chargé et affiché
let decodeCtx = null;     // AudioContext partagé (un seul par page)

function visemeLanguage(lang) {
  const short = String(lang || 'fr').toLowerCase().split('-')[0];
  return VISEME_LANGUAGES.includes(short) ? short : 'en';
}

function audioContext() {
  if (!decodeCtx) {
    decodeCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  return decodeCtx;
}

/** Pause que la voix marque APRÈS une ponctuation, en ms. Mesuré le 2026-10-13 sur Kokoro
 *  (voix française, trois réponses réelles) : 180 à 340 ms après « ! . : », de rien à près de
 *  0,5 s après une virgule — d'où une moyenne. Avec ces valeurs, 8 reprises de phrase sur 9
 *  tombent à moins de 100 ms de la voix, la pire à 315 ms (1 135 ms au prorata des lettres). */
const PAUSE_AFTER_MS = { '.': 250, '!': 250, '?': 250, '…': 250, ':': 200, ';': 200, ',': 100 };

/** Part du silence que l'estimation s'autorise : au-delà, elle se fie aux mots. */
const MAX_PAUSE_SHARE = 0.4;

/** Poids PARLÉ d'un mot : ses lettres, et quatre par chiffre — un chiffre se dit en un mot
 *  (« zéro », « cinq »). Mesuré : « DSC05016.jpg » (12 caractères) décalait la suite de 1,1 s. */
function spokenWeight(word) {
  const letters = (word.match(/\p{L}/gu) || []).length;
  const digits = (word.match(/\d/g) || []).length;
  return letters + 4 * digits || 1;
}

/**
 * Répartit les mots sur la durée réelle de l'audio, au prorata de leur POIDS PARLÉ, en
 * réservant aux ponctuations fortes la pause que la voix y marque.
 *
 * Kokoro ne nous rend pas de timestamps en français : son calcul interne (`join_timestamps`,
 * exact par construction) n'existe que sur la branche anglaise. L'alignement approché est
 * l'arbitrage acté pour le pilote. La voie exacte (remonter les timestamps de Kokoro) reste
 * ouverte, et le catalogue sait déjà DIRE si un moteur en fournit (`timestamp_languages`).
 *
 * ⚠ L'estimation ne tient que sur un audio COURT : son erreur s'accumule du début à la fin. D'où
 * le découpage en groupes de phrases de `wama-assistant-voice.js` (`takeSentences`). Jusqu'au
 * 2026-10-13 elle ignorait les pauses et les chiffres : mesuré sur une réponse de 12 s, la
 * phrase qui suit « DSC05016.jpg » était estimée 1,1 s trop tôt.
 *
 * `leadMs` décale tous les mots : la latence de sortie du navigateur (voir `speak`).
 */
function estimateTimings(text, durationMs, leadMs = 0) {
  const words = String(text || '').trim().split(/\s+/).filter(Boolean);
  if (!words.length || !durationMs) return null;
  const pauses = words.map((w, i) => (i < words.length - 1 ? PAUSE_AFTER_MS[w.slice(-1)] || 0 : 0));
  const pauseTotal = pauses.reduce((n, p) => n + p, 0);
  const pauseScale = pauseTotal > MAX_PAUSE_SHARE * durationMs
    ? (MAX_PAUSE_SHARE * durationMs) / pauseTotal : 1;
  const weights = words.map(spokenWeight);
  const weightTotal = weights.reduce((n, w) => n + w, 0);
  const speechMs = durationMs - pauseTotal * pauseScale;
  const wtimes = [];
  const wdurations = [];
  let t = 0;
  words.forEach((word, i) => {
    const part = (weights[i] / weightTotal) * speechMs;
    wtimes.push(Math.round(t + leadMs));
    wdurations.push(Math.round(part));
    t += part + pauses[i] * pauseScale;
  });
  return { words, wtimes, wdurations };
}

/** Ce que le navigateur met entre le départ d'un son et sa sortie au haut-parleur, en ms.
 *  Quelques ms sur une carte son, 150 à 300 sur un casque Bluetooth — davantage quand le micro
 *  est ouvert (conversation vocale) ; TalkingHead, lui, anime les lèvres au départ du son. */
function outputLatencyMs() {
  const ctx = head && head.audioCtx;
  if (!ctx) return 0;
  return Math.round(1000 * ((ctx.outputLatency || 0) + (ctx.baseLatency || 0)));
}

/** Cadrage du VOLET de l'assistant — le défaut de `init` (réglé au navigateur le 2026-09-22). */
export const PANEL_CAMERA = { cameraView: 'upper', cameraDistance: -1.5, cameraY: -0.06 };

/**
 * Crée l'avatar dans `node`. Idempotent : un second appel ne recrée rien.
 * @param {HTMLElement} node conteneur (doit avoir une taille non nulle)
 * @param {{glbUrl: string, lang?: string, mood?: string, body?: string,
 *          camera?: Object, headOptions?: Object}} opts
 *   `camera` surcharge le cadrage (`cameraView`, `cameraDistance`, `cameraX`, `cameraY`,
 *   `cameraRotateX`, `cameraRotateY`) — défaut PANEL_CAMERA. `headOptions` : autres options
 *   TalkingHead (ex. `modelFPS` pour le rendu vidéo image par image, 2026-09-30).
 */
export async function init(node, opts) {
  if (head || !node) return head;
  const lang = visemeLanguage(opts && opts.lang);
  const camera = Object.assign({}, PANEL_CAMERA, (opts && opts.camera) || {});
  head = new TalkingHead(node, Object.assign({
    // Pas de `ttsEndpoint` : la synthèse reste côté WAMA (Kokoro), on ne fait que RENDRE.
    // Le laisser vide évite que TalkingHead tente son propre TTS.
    ttsEndpoint: '',
    lipsyncModules: VISEME_LANGUAGES,
    lipsyncLang: lang,          // défaut de la lib = 'fi' (finnois) — à écraser explicitement
    // CADRAGE (Fabien, 2026-09-22 : « beaucoup de marge vide autour de l'avatar ») — mesuré au
    // navigateur sur un volet de 329 px de large : la vue « upper » par défaut (caméra à
    // z = 4,5) laissait un tiers de vide au-dessus de la tête ; « head » coupe le menton et
    // les épaules. On garde « upper » et on RAPPROCHE la caméra (`cameraDistance` s'ajoute à
    // z : −1,7 → z ≈ 2,8), légèrement relevée : visage et épaules remplissent 200 px de haut.
    // 2ᵉ mesure (Fabien : « le front est un peu mangé en haut ») : caméra un peu moins proche et
    // RELEVÉE (`cameraY` négatif = caméra plus haute = avatar plus bas dans le cadre).
    // Ces valeurs sont PANEL_CAMERA ; un appelant (rendu vidéo) les surcharge par `opts.camera`.
    avatarMood: (opts && opts.mood) || 'neutral',
  }, camera, (opts && opts.headOptions) || {}));
  await head.showAvatar({
    url: opts.glbUrl,
    body: (opts && opts.body) || 'F',
    avatarMood: (opts && opts.mood) || 'neutral',
    lipsyncLang: lang,
  });
  ready = true;
  return head;
}

/** Vrai si l'avatar est chargé et peut parler. */
export function isReady() {
  return ready && !!head;
}

/**
 * Fait parler l'avatar sur un audio DÉJÀ synthétisé (Blob WAV rendu par /api/tts-kokoro/).
 * Rend `true` si l'avatar a pris la parole, `false` s'il n'était pas prêt — l'appelant peut
 * alors jouer l'audio normalement (dégradation douce : on ne perd JAMAIS la voix).
 * `options.live` (vrai par défaut) : le son sort au haut-parleur, les lèvres attendent donc la
 * latence de sortie ; le rendu vidéo image par image passe `{live: false}`.
 */
export async function speak(blob, text, lang, timings, options = {}) {
  if (!isReady() || !blob) return false;
  try {
    const buf = await blob.arrayBuffer();
    // decodeAudioData CONSOMME l'ArrayBuffer : ne pas le réutiliser après cet appel.
    const audio = await audioContext().decodeAudioData(buf);
    // `timings` ({words, wtimes, wdurations}, ms) — MESURÉS quand l'appelant les a (mots datés par
    // la transcription, rendu vidéo du 2026-09-30) ; sinon l'estimation.
    const leadMs = options.live === false ? 0 : outputLatencyMs();
    timings = timings || estimateTimings(text, audio.duration * 1000, leadMs);
    const r = { audio };
    if (timings) Object.assign(r, timings);
    head.speakAudio(r, { lipsyncLang: visemeLanguage(lang) });
    return true;
  } catch (e) {
    console.error('[WamaAvatar] speak a échoué — repli sur la voix seule', e);
    return false;
  }
}

// ── La voix AU FIL DE L'EAU (2026-10-28) ──────────────────────────────────────────────────
// Le service rend le PCM à mesure qu'il le calcule (`/tts/stream`) ; TalkingHead sait le jouer
// en flux (`streamStart` / `streamAudio` / `streamNotifyEnd`, son module `playback-worklet.js`).
// Ce qui manque au flux, c'est la DURÉE : les lèvres se calent sur les mots, et l'estimation
// d'`estimateTimings` répartit les mots sur la durée de l'audio, inconnue avant la fin. Elle est
// donc PRÉDITE au débit de parole APPRIS : millisecondes par unité de poids parlé
// (`spokenWeight`), recalées à la fin de chaque morceau sur la durée réellement reçue — la
// suivante se cale sur la voix du moment. Départ : 75 ms, mesuré sur Phonon et Kokoro
// (« Bonjour, je suis l'assistant de WAMA. » : 2,56 s pour 29 lettres et deux pauses).
let msPerWeight = 75;
const LEARN = 0.5;          // part de la dernière mesure dans le débit appris

function predictedMs(text) {
  const words = String(text || '').trim().split(/\s+/).filter(Boolean);
  const pauses = words.reduce((n, w, i) => n + (i < words.length - 1 ? PAUSE_AFTER_MS[w.slice(-1)] || 0 : 0), 0);
  return { weight: words.reduce((n, w) => n + spokenWeight(w), 0), pauses };
}

/**
 * Un lecteur EN FLUX qui fait parler l'avatar — la forme d'un `Audio` (`start`, `pause`, `paused`,
 * `ended`, événements `ended`/`error`/`pause`, `received`), comme celui du canal commun
 * (`WamaApp.Speech.stream`) : la voix de l'assistant le joue par le même canal, et l'arrêt passe
 * par le même chemin. Il lit sa réponse dès sa création ; il ne parle qu'à `start()`.
 */
export function streamPlayer(response, rate, text, lang) {
  const listeners = { ended: [], error: [], pause: [] };
  const fire = (type) => (listeners[type] || []).forEach((fn) => { try { fn(); } catch (_) {} });
  const pending = [];
  let started = false, finished = false, first = true, samples = 0;
  const shape = predictedMs(text);
  const player = {
    paused: false, ended: false,
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    async start() {
      if (!isReady()) { player.ended = true; fire('error'); return; }
      try {
        await head.streamStart({ sampleRate: rate, lipsyncLang: visemeLanguage(lang),
                                 lipsyncType: 'words', waitForAudioChunks: true },
                               null, () => finish());
      } catch (e) {
        console.error('[WamaAvatar] flux refusé', e);
        player.ended = true; fire('error'); return;
      }
      if (player.paused) return;
      started = true;
      pending.splice(0).forEach(send);
      if (finished) head.streamNotifyEnd();
    },
    pause() {
      if (player.paused || player.ended) return;
      player.paused = true;
      reading.cancel();
      if (started) { try { head.streamInterrupt(); } catch (_) {} }
      fire('pause');
    },
  };
  function send(buffer) {
    if (player.paused) return;
    const r = { audio: buffer };
    if (first) {
      // Les mots partent avec le premier morceau, sur la durée PRÉDITE (voir `msPerWeight`).
      Object.assign(r, estimateTimings(text, shape.weight * msPerWeight + shape.pauses,
                                       outputLatencyMs()) || {});
      first = false;
    }
    head.streamAudio(r);
  }
  function finish() {
    if (player.ended || player.paused) return;
    // Le débit APPRIS : la durée réellement dite, contre celle qu'on avait prédite.
    const spokenMs = (1000 * samples) / rate - shape.pauses;
    if (shape.weight > 3 && spokenMs > 0) {
      msPerWeight = (1 - LEARN) * msPerWeight + LEARN * (spokenMs / shape.weight);
    }
    player.ended = true;
    fire('ended');
  }
  const reading = window.WamaApp.Speech.readPcm16(response, (buffer) => {
    samples += buffer.byteLength / 2;
    if (started) send(buffer); else pending.push(buffer);
  });
  player.received = reading.done.then(() => {
    finished = true;
    if (started && !player.paused) head.streamNotifyEnd();
  }, () => {
    finished = true;
    if (!player.paused && !player.ended) { player.ended = true; fire('error'); }
  });
  return player;
}

/** Coupe la parole en cours (l'utilisateur a relancé une requête) — flux compris. */
export function stop() {
  if (head) {
    try { if (head.isStreaming) head.streamInterrupt(); } catch (_) {}
    try { head.stopSpeaking(); } catch (_) {}
  }
}

// Monté en global : le JS de l'assistant est un script CLASSIQUE (pas un module) et ne peut
// pas `import` ce fichier. Même convention que WamaApp/WamaParams.
/** L'instance TalkingHead (null tant que l'avatar n'est pas chargé) — pour le cadrage
 *  (`setView`) et les sondes de mise au point ; le rendu reste le sien. */
export function instance() {
  return head;
}

// `outputLatencyMs` : la voix s'en sert pour savoir jusqu'à quand elle est encore AUDIBLE — c'est
// là que l'écoute de la conversation doit encore la tenir pour la sienne (écho, 2026-10-13).
window.WamaAvatar = { init, speak, streamPlayer, isReady, stop, instance, outputLatencyMs };
