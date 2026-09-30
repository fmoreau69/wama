/**
 * WamaAvatarRender — rend l'avatar 3D parlant IMAGE PAR IMAGE, pour en faire une vidéo.
 *
 * POURQUOI CE MODULE (2026-09-30). `wama-avatar.js` fait parler l'avatar de l'assistant en TEMPS
 * RÉEL. Pour produire une vidéo (moteur `talkinghead` de l'avatarizer), l'enregistrement en temps
 * réel ne tient pas : MESURÉ, MediaRecorder capte ~21 i/s sur la 4090 (l'encodeur limite) et
 * ~5,7 i/s en rendu CPU — la vidéo saccade et sa cadence dépend de la machine. Ici le TEMPS EST
 * PILOTÉ : la boucle `requestAnimationFrame` de TalkingHead est coupée, et chaque image est
 * produite par un appel explicite à `animate(t)` avec un pas fixe (40 ms = 25 i/s). La vidéo a
 * donc exactement la cadence voulue, quelle que soit la vitesse du rendu.
 *
 * Ce module ne refait RIEN de `wama-avatar.js` : chargement, visèmes, timings de mots viennent de
 * lui (`window.WamaAvatar`). Il ajoute seulement l'horloge et la capture.
 *
 * Le SON ne passe pas par ici : le serveur multiplexe le WAV d'origine avec ffmpeg. Pour le caler,
 * on relève le moment où TalkingHead programme l'audio — ses lèvres sont datées sur `animClock`
 * (`talkinghead.mjs`, playAudio : `ts = animClock + x + delay`, `source.start(now + delay)`).
 *
 * ⚠ MODULE ES6, chargé APRÈS l'importmap commune et `wama-avatar.js`.
 */

let head = null;
let canvas = null;
let frame = null;         // canevas 2D de COMPOSITION : fond + rendu WebGL
let frameCtx = null;
let background = '#f4f1ea';
let stepMs = 40;
let speechStart = null;   // {clock, delayMs} relevé quand TalkingHead programme l'audio

/** Coupe la boucle temps réel : à partir d'ici, seule `step()` fait avancer l'avatar. */
function freezeRealtimeLoop() {
  window.requestAnimationFrame = () => 0;
  if (head._raf) cancelAnimationFrame(head._raf);
}

/** Relève (animClock, delay) au moment où TalkingHead démarre la source audio de la parole. */
function watchSpeechStart() {
  const ctx = head.audioCtx;
  const create = ctx.createBufferSource.bind(ctx);
  ctx.createBufferSource = () => {
    const source = create();
    const start = source.start.bind(source);
    source.start = (when = 0, ...rest) => {
      if (!speechStart) {
        speechStart = { clock: head.animClock, delayMs: Math.max(0, (when - ctx.currentTime) * 1000) };
      }
      return start(when, ...rest);
    };
    return source;
  };
}

/** Avance l'horloge d'UN pas (sans capture). */
function tick() {
  head.animate(head.animTimeLast + stepMs);
}

/**
 * Charge l'avatar et coupe la boucle temps réel.
 * @param {{glbUrl: string, lang?: string, mood?: string, body?: string, camera?: Object,
 *          fps?: number, warmupMs?: number, background?: string}} opts
 */
export async function prepare(opts) {
  const node = document.getElementById('avatar');
  stepMs = 1000 / (opts.fps || 25);
  head = await window.WamaAvatar.init(node, {
    glbUrl: opts.glbUrl, lang: opts.lang, mood: opts.mood, body: opts.body, camera: opts.camera,
    // animate() ignore un pas plus court que 1000/modelFPS (défaut 30 i/s = 33 ms) : on l'abaisse
    // pour que CHAQUE pas demandé produise une image, quelle que soit la cadence choisie.
    headOptions: { modelFPS: 120 },
  });
  canvas = node.querySelector('canvas');
  // Le canevas WebGL est TRANSPARENT : exporté tel quel en JPEG, son fond sort NOIR (vécu au 1ᵉʳ
  // rendu du 2026-09-30). Chaque image est donc composée sur un fond explicite — c'est aussi là
  // qu'un décor viendra se glisser.
  background = opts.background || background;
  frame = document.createElement('canvas');
  frame.width = canvas.width;
  frame.height = canvas.height;
  frameCtx = frame.getContext('2d');
  freezeRealtimeLoop();
  watchSpeechStart();
  // Échauffement non enregistré : la pose de repos s'installe (sinon 1ʳᵉ image en T-pose).
  const warm = Math.ceil((opts.warmupMs ?? 1000) / stepMs);
  for (let i = 0; i < warm; i++) tick();
  const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
  const dbg = gl && gl.getExtension('WEBGL_debug_renderer_info');
  return {
    width: canvas.width, height: canvas.height, stepMs,
    renderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : null,
  };
}

/**
 * Programme la parole (WAV en base64) et rend l'horloge de l'image 0 et le départ de l'audio.
 * `audioOffsetMs` = instant, dans la VIDÉO, où le son doit commencer pour tomber sur les lèvres.
 */
export async function speak(wavBase64, text, lang) {
  const bytes = Uint8Array.from(atob(wavBase64), c => c.charCodeAt(0));
  const clock0 = head.animClock;
  speechStart = null;
  const ok = await window.WamaAvatar.speak(new Blob([bytes], { type: 'audio/wav' }), text, lang);
  if (!ok) throw new Error("l'avatar n'a pas pris la parole (WamaAvatar.speak a refusé)");
  // TalkingHead programme l'audio en asynchrone : on laisse tourner la boucle d'événements
  // (sans avancer l'horloge) jusqu'au relevé.
  for (let i = 0; i < 200 && !speechStart; i++) await new Promise(r => setTimeout(r, 10));
  if (!speechStart) throw new Error("départ de l'audio jamais relevé (TalkingHead n'a rien joué)");
  return { clock0, audioOffsetMs: speechStart.clock + speechStart.delayMs - clock0 };
}

/** Rend `count` images (JPEG base64, sans préfixe) en avançant l'horloge d'un pas chacune. */
export function step(count, quality = 0.92) {
  const frames = [];
  for (let i = 0; i < count; i++) {
    tick();
    // Lecture dans la MÊME tâche que le rendu : le tampon WebGL est encore valide.
    frameCtx.fillStyle = background;
    frameCtx.fillRect(0, 0, frame.width, frame.height);
    frameCtx.drawImage(canvas, 0, 0);
    frames.push(frame.toDataURL('image/jpeg', quality).slice('data:image/jpeg;base64,'.length));
  }
  return frames;
}

window.WamaAvatarRender = { prepare, speak, step };
