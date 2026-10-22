/* ==========================================================================
   WAMA — les MAINS qui pilotent une scène 3D, par la webcam (2026-10-22, demande de Fabien :
   « en serrant la main, puis en déplaçant la main, ça fait tourner la 3D ; avec les deux mains,
   on zoome et dézoome »).

   Le geste se reconnaît DANS LE NAVIGATEUR — MediaPipe Gesture Recognizer (Apache-2.0), vendorisé
   (`static/vendors/mediapipe-tasks-vision-*`, importmap `mediapipe/tasks-vision`) : aucune image de
   la webcam ne quitte la page. Le modèle est une ligne du catalogue, installée par la route
   (`common/hand_gestures.py`), servie par `common:hand_model`.

   Deux parties :
     - `HandGestures` : l'INTERPRÉTATION, pure (aucun DOM) — des mains repérées image par image →
       une rotation (un poing qui se déplace) ou un zoom (deux poings qui s'écartent) ;
     - `startHands` : la caméra, MediaPipe et la vignette — chargés seulement quand on allume les
       mains (`import()` paresseux), éteints avec elles.
   Consommateur : la brique des constellations (`wama-constellation.js`, puce « Mains »).
   ========================================================================== */

// Les repères de la paume (poignet et bases des quatre doigts) : leur moyenne suit la main sans
// trembler avec les doigts qui se ferment.
const PALM = [0, 5, 9, 13, 17];
const FIST = 'Closed_Fist';

/** Des mains repérées → des gestes de caméra. Une instance par session de mains. */
export class HandGestures {
  constructor({ smoothing = 0.55, holdFrames = 2, releaseFrames = 4, deadZone = 0.0025, minScore = 0.55 } = {}) {
    Object.assign(this, { smoothing, holdFrames, releaseFrames, deadZone, minScore });
    this.hands = new Map();          // main (gauche/droite) → { fist, on, off, palm, prev }
    this.prevDist = null;
  }

  // Un poing se DÉCLARE après `holdFrames` images, se relâche après `releaseFrames` : une image
  // mal lue ne fait ni lâcher ni saisir la scène.
  _track(h) {
    let t = this.hands.get(h.id);
    if (!t) { t = { fist: false, on: 0, off: 0, palm: { ...h.palm }, prev: null, seen: true }; this.hands.set(h.id, t); }
    t.seen = true;
    const closed = h.gesture === FIST && (h.score ?? 1) >= this.minScore;
    if (closed) { t.on += 1; t.off = 0; if (t.on >= this.holdFrames) t.fist = true; }
    else { t.off += 1; t.on = 0; if (t.off >= this.releaseFrames) { t.fist = false; t.prev = null; } }
    // Lissage exponentiel : la paume suit la main sans reprendre son tremblement.
    const a = 1 - this.smoothing;
    t.palm.x += a * (h.palm.x - t.palm.x);
    t.palm.y += a * (h.palm.y - t.palm.y);
    return t;
  }

  /**
   * `hands` : `[{id, gesture, score, palm: {x, y}}]`, coordonnées NORMALISÉES de l'image (0 → 1).
   * Rend `{mode, rotate: {dx, dy} | null, zoom: facteur | null}` — `dx` est déjà en MIROIR (la
   * main droite qui va à droite fait tourner vers la droite), `zoom` < 1 rapproche.
   */
  update(hands) {
    for (const t of this.hands.values()) t.seen = false;
    for (const h of hands) this._track(h);
    for (const [id, t] of this.hands) if (!t.seen) this.hands.delete(id);      // main sortie du champ
    const fists = [...this.hands.values()].filter(t => t.fist);
    if (fists.length >= 2) {
      for (const t of this.hands.values()) t.prev = null;
      const [a, b] = fists;
      const dist = Math.hypot(a.palm.x - b.palm.x, a.palm.y - b.palm.y);
      const prev = this.prevDist;
      this.prevDist = dist;
      if (prev == null || dist < 1e-3) return { mode: 'zoom', rotate: null, zoom: null };
      const f = prev / dist;
      return { mode: 'zoom', rotate: null, zoom: Math.abs(f - 1) < this.deadZone ? null : f };
    }
    this.prevDist = null;
    if (fists.length === 1) {
      const t = fists[0];
      const prev = t.prev;
      t.prev = { ...t.palm };
      if (!prev) return { mode: 'rotate', rotate: null, zoom: null };
      const dx = -(t.palm.x - prev.x), dy = t.palm.y - prev.y;
      if (Math.hypot(dx, dy) < this.deadZone) return { mode: 'rotate', rotate: null, zoom: null };
      return { mode: 'rotate', rotate: { dx, dy }, zoom: null };
    }
    return { mode: hands.length ? 'open' : 'none', rotate: null, zoom: null };
  }
}

const palmOf = lm => {
  let x = 0, y = 0;
  for (const i of PALM) { x += lm[i].x; y += lm[i].y; }
  return { x: x / PALM.length, y: y / PALM.length };
};

// Le résultat de MediaPipe → les mains telles que `HandGestures` les lit.
export function handsFromResult(res) {
  return (res.landmarks || []).map((lm, i) => {
    const g = ((res.gestures || [])[i] || [])[0] || {};
    const side = ((res.handedness || [])[i] || [])[0] || {};
    return { id: side.categoryName || String(i), gesture: g.categoryName || 'None', score: g.score, palm: palmOf(lm), landmarks: lm };
  });
}

const STATUS = {
  loading: 'Chargement des mains…',
  none: 'Montrez une main à la caméra',
  open: 'Fermez le poing pour saisir la scène',
  rotate: 'Poing fermé : la scène tourne',
  zoom: 'Deux poings : écartez pour zoomer',
};

/**
 * Allume les mains dans `box` (la vignette de la scène). `wasm` : dossier des moteurs ;
 * `model` : adresse du modèle ; `manage` : page où l'installer ; `onGesture(out)` : chaque image.
 * Rend `{stop}`.
 */
export async function startHands(box, { wasm, model, manage, onGesture, onError }) {
  const status = box.querySelector('.wc-hands-status');
  const say = (text, isError = false) => { status.innerHTML = text; box.classList.toggle('error', isError); };
  const fail = html => { say(html, true); if (onError) onError(); return { stop() {} }; };
  say(STATUS.loading);
  if (!window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return fail("La caméra demande une connexion sécurisée (https, ou l'adresse localhost).");
  }
  const head = await fetch(model, { method: 'HEAD', credentials: 'same-origin' }).catch(() => null);
  if (!head || !head.ok) {
    return fail(`Le modèle des gestes n'est pas installé. <a href="${manage}">Gestion des modèles</a> → « MediaPipe Gesture Recognizer ».`);
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, facingMode: 'user' }, audio: false });
  } catch (e) {
    return fail(`Caméra indisponible (${e.name === 'NotAllowedError' ? 'accès refusé' : e.message}).`);
  }
  const video = box.querySelector('video'), canvas = box.querySelector('canvas'), g = canvas.getContext('2d');
  video.srcObject = stream;
  await video.play().catch(() => {});
  // Le moteur de MediaPipe écrit ses lignes d'INFORMATION (« INFO: Created TensorFlow Lite XNNPACK
  // delegate… ») sur `console.error` : rendues à `console.info` le temps des mains — une vraie
  // erreur reste une erreur.
  const consoleError = console.error;
  console.error = (...args) => (typeof args[0] === 'string' && args[0].startsWith('INFO:')
    ? console.info(...args) : consoleError(...args));
  // ⚠ RIEN NE QUITTE WAMA (mesuré le 2026-10-22 par le scénario nocturne) : la librairie envoie
  // d'elle-même une télémétrie d'usage à Google (`POST https://odml.pa.googleapis.com/v1/log`,
  // toutes les 60 s), sans option publique pour la couper. Le temps des mains, tout `fetch` vers
  // une AUTRE origine que WAMA reçoit un refus LOCAL, sans atteindre le réseau — son journaliseur
  // s'arrête alors de lui-même (il efface son minuteur sur erreur). La page n'a aucun appel
  // légitime hors de son origine (aucun CDN, règle de WAMA).
  const pageFetch = window.fetch;
  window.fetch = (input, init) => {
    const url = new URL(typeof input === 'string' ? input : (input.url || input.href || String(input)), location.href);
    const local = url.origin === location.origin || url.protocol === 'data:' || url.protocol === 'blob:';
    return local ? pageFetch(input, init)
      : Promise.resolve(new Response(null, { status: 403, statusText: 'WAMA : hors de la page' }));
  };
  const restorePage = () => { console.error = consoleError; window.fetch = pageFetch; };
  let recognizer;
  try {
    const { FilesetResolver, GestureRecognizer } = await import('mediapipe/tasks-vision');
    const fileset = await FilesetResolver.forVisionTasks(wasm);
    const make = delegate => GestureRecognizer.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: model, delegate }, runningMode: 'VIDEO', numHands: 2 });
    recognizer = await make('GPU').catch(() => make('CPU'));
  } catch (e) {
    stream.getTracks().forEach(t => t.stop());
    restorePage();
    return fail(`Les mains n'ont pas pu démarrer (${e.message}).`);
  }
  const gestures = new HandGestures();
  let running = true, lastTime = -1, raf = 0;
  // Les repères : couleur du lien pour un poing, de l'encre sinon — jetons de la feuille commune.
  const look = getComputedStyle(box);
  const ink = { fist: look.getPropertyValue('--wc-share').trim(), open: look.getPropertyValue('--wc-ink').trim() };
  const draw = hands => {
    canvas.width = video.videoWidth || 640; canvas.height = video.videoHeight || 480;
    g.clearRect(0, 0, canvas.width, canvas.height);
    for (const h of hands) {
      g.fillStyle = h.gesture === FIST ? ink.fist : ink.open;
      for (const p of h.landmarks) { g.beginPath(); g.arc(p.x * canvas.width, p.y * canvas.height, 3, 0, 6.283); g.fill(); }
    }
  };
  const loop = () => {
    if (!running) return;
    if (video.readyState >= 2 && video.currentTime !== lastTime) {
      lastTime = video.currentTime;
      const hands = handsFromResult(recognizer.recognizeForVideo(video, performance.now()));
      const out = gestures.update(hands);
      draw(hands);
      say(STATUS[out.mode] || STATUS.none);
      onGesture(out);
    }
    raf = requestAnimationFrame(loop);
  };
  raf = requestAnimationFrame(loop);
  return {
    stop() {
      running = false; cancelAnimationFrame(raf);
      stream.getTracks().forEach(t => t.stop());
      video.srcObject = null;
      try { recognizer.close(); } catch (e) { /* déjà fermé */ }
      restorePage();
    },
  };
}
