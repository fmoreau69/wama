/* ==========================================================================
   WAMA — les MAINS qui pilotent une scène 3D, par la webcam (2026-10-22, demandes de Fabien :
   « en serrant la main, puis en déplaçant la main, ça fait tourner la 3D ; avec les deux mains,
   on zoome et dézoome » ; puis « voir mes mains avec des mains virtuelles dans la scène pour
   pouvoir cliquer et interagir avec les boutons » ; et « élargir le champ de la caméra »).

   Le geste se reconnaît DANS LE NAVIGATEUR — MediaPipe Gesture Recognizer (Apache-2.0), vendorisé
   (`static/vendors/mediapipe-tasks-vision-*`, importmap `mediapipe/tasks-vision`) : aucune image de
   la webcam ne quitte la page. Le modèle est une ligne du catalogue, installée par la route
   (`common/hand_gestures.py`), servie par `common:hand_model`.

   Deux parties :
     - `HandGestures` : l'INTERPRÉTATION, pure (aucun DOM) — des mains repérées image par image →
       une rotation (un poing qui se déplace), un zoom (deux poings qui s'écartent), ou un POINTEUR
       (le bout de l'index d'une main ouverte) qui CLIQUE quand le pouce et l'index se pincent ;
     - `startHands` : la caméra (et ses réglages), MediaPipe et la vignette — chargés seulement
       quand on allume les mains (`import()` paresseux), éteints avec elles.
   Consommateur : la brique des constellations (`wama-constellation.js`, icône de main), qui
   dessine les mains virtuelles sur la scène et y porte le clic.
   ========================================================================== */

// Les repères de la paume (poignet et bases des quatre doigts) : leur moyenne suit la main sans
// trembler avec les doigts qui se ferment.
const PALM = [0, 5, 9, 13, 17];
const WRIST = 0, MIDDLE_BASE = 9, THUMB_TIP = 4, INDEX_TIP = 8;
const FIST = 'Closed_Fist';
// Les os de la main (21 repères de MediaPipe) : de quoi dessiner une main virtuelle.
export const HAND_BONES = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10],
  [10, 11], [11, 12], [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [0, 17], [17, 18], [18, 19], [19, 20]];

const clamp01 = v => Math.min(1, Math.max(0, v));
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

/** Coordonnées de l'image → coordonnées de la SCÈNE (0 → 1), en miroir, avec une MARGE : les bords
 *  de la scène s'atteignent sans que la main sorte du champ de la caméra. */
export function toScene(p, margin = 0.12) {
  return { x: clamp01((1 - p.x - margin) / (1 - 2 * margin)), y: clamp01((p.y - margin) / (1 - 2 * margin)) };
}

/** Des mains repérées → des gestes. Une instance par session de mains. */
export class HandGestures {
  constructor({ smoothing = 0.55, holdFrames = 2, releaseFrames = 4, deadZone = 0.0025, minScore = 0.55,
                pinchOn = 0.28, pinchOff = 0.42, margin = 0.12 } = {}) {
    Object.assign(this, { smoothing, holdFrames, releaseFrames, deadZone, minScore, pinchOn, pinchOff, margin });
    this.hands = new Map();          // main (gauche/droite) → { fist, on, off, palm, prev, pinch… }
    this.prevDist = null;
  }

  // Un poing se DÉCLARE après `holdFrames` images, se relâche après `releaseFrames` : une image
  // mal lue ne fait ni lâcher ni saisir la scène. Même hystérésis pour le pincement.
  _track(h) {
    let t = this.hands.get(h.id);
    if (!t) { t = { fist: false, on: 0, off: 0, palm: { ...h.palm }, prev: null, pinch: false, pinchOn: 0, tip: null, seen: true }; this.hands.set(h.id, t); }
    t.seen = true;
    const closed = h.gesture === FIST && (h.score ?? 1) >= this.minScore;
    if (closed) { t.on += 1; t.off = 0; if (t.on >= this.holdFrames) t.fist = true; }
    else { t.off += 1; t.on = 0; if (t.off >= this.releaseFrames) { t.fist = false; t.prev = null; } }
    // Lissage exponentiel : la paume suit la main sans reprendre son tremblement.
    const a = 1 - this.smoothing;
    t.palm.x += a * (h.palm.x - t.palm.x);
    t.palm.y += a * (h.palm.y - t.palm.y);
    t.clicked = false;
    if (h.tips && h.size) {
      const tip = toScene(h.tips.index, this.margin);
      t.tip = t.tip ? { x: t.tip.x + a * (tip.x - t.tip.x), y: t.tip.y + a * (tip.y - t.tip.y) } : tip;
      const ratio = dist(h.tips.thumb, h.tips.index) / h.size;
      if (ratio < this.pinchOn) { t.pinchOn += 1; if (t.pinchOn >= this.holdFrames && !t.pinch) { t.pinch = true; t.clicked = true; } }
      else { t.pinchOn = 0; if (ratio > this.pinchOff) t.pinch = false; }
    } else t.tip = null;
    return t;
  }

  /**
   * `hands` : `[{id, gesture, score, palm: {x, y}, tips?: {thumb, index}, size?}]`, coordonnées
   * NORMALISÉES de l'image (0 → 1). Rend `{mode, rotate: {dx, dy} | null, zoom: facteur | null,
   * pointer: {x, y} | null, click}` — `dx` est déjà en MIROIR (la main droite qui va à droite fait
   * tourner vers la droite), `zoom` < 1 rapproche, `pointer` est en coordonnées de la SCÈNE et
   * `click` vaut vrai à l'image où le pincement se ferme.
   */
  update(hands) {
    for (const t of this.hands.values()) t.seen = false;
    for (const h of hands) this._track(h);
    for (const [id, t] of this.hands) if (!t.seen) this.hands.delete(id);      // main sortie du champ
    const none = { rotate: null, zoom: null, pointer: null, click: false };
    const fists = [...this.hands.values()].filter(t => t.fist);
    if (fists.length >= 2) {
      for (const t of this.hands.values()) t.prev = null;
      const [a, b] = fists;
      const d = Math.hypot(a.palm.x - b.palm.x, a.palm.y - b.palm.y);
      const prev = this.prevDist;
      this.prevDist = d;
      if (prev == null || d < 1e-3) return { ...none, mode: 'zoom' };
      const f = prev / d;
      return { ...none, mode: 'zoom', zoom: Math.abs(f - 1) < this.deadZone ? null : f };
    }
    this.prevDist = null;
    if (fists.length === 1) {
      const t = fists[0];
      const prev = t.prev;
      t.prev = { ...t.palm };
      if (!prev) return { ...none, mode: 'rotate' };
      const dx = -(t.palm.x - prev.x), dy = t.palm.y - prev.y;
      if (Math.hypot(dx, dy) < this.deadZone) return { ...none, mode: 'rotate' };
      return { ...none, mode: 'rotate', rotate: { dx, dy } };
    }
    // Une main OUVERTE qui porte ses doigts : le pointeur, et le clic du pincement.
    const pointing = [...this.hands.values()].find(t => t.tip);
    if (pointing) return { ...none, mode: pointing.pinch ? 'pinch' : 'point', pointer: { ...pointing.tip }, click: pointing.clicked };
    return { ...none, mode: hands.length ? 'open' : 'none' };
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
    return { id: side.categoryName || String(i), gesture: g.categoryName || 'None', score: g.score, palm: palmOf(lm),
             tips: { thumb: lm[THUMB_TIP], index: lm[INDEX_TIP] }, size: dist(lm[WRIST], lm[MIDDLE_BASE]), landmarks: lm };
  });
}

const STATUS = {
  loading: 'Chargement des mains…',
  none: 'Montrez une main à la caméra',
  open: 'Fermez le poing pour saisir la scène',
  point: 'Index : pointez · pincez pour cliquer · poing : tourner',
  pinch: 'Pincement : clic',
  rotate: 'Poing fermé : la scène tourne',
  zoom: 'Deux poings : écartez pour zoomer',
};

// ── Réglages de la caméra (demande de Fabien, 2026-10-22 : « le champ est trop étroit, mes mains
// sortent trop vite du champ ») ─────────────────────────────────────────────────────────────
// Gardés dans le NAVIGATEUR, pas au compte : une caméra (son identifiant, ses capacités) n'existe
// que sur cette machine. Lecture et écriture protégées (stockage refusé : les défauts valent).
export const HAND_DEFAULTS = { deviceId: '', wide: true, zoom: null, sensitivity: 1.5 };
const SETTINGS_KEY = 'wama.hands';
function loadSettings() {
  try { return { ...HAND_DEFAULTS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}') }; }
  catch (e) { return { ...HAND_DEFAULTS }; }
}
function saveSettings(s) { try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(s)); } catch (e) { /* sans stockage */ } }

/** Ce qu'on demande à la caméra. LARGE = 16:9 en haute définition : la plupart des webcams
 *  RECADRENT leur capteur en 4:3 (640 × 480), ce qui rétrécit le champ à l'horizontale. */
export function cameraConstraints(s) {
  const size = s.wide ? { width: { ideal: 1920 }, height: { ideal: 1080 }, aspectRatio: { ideal: 16 / 9 } }
    : { width: { ideal: 640 }, height: { ideal: 480 }, aspectRatio: { ideal: 4 / 3 } };
  return { video: { ...size, ...(s.deviceId ? { deviceId: { exact: s.deviceId } } : { facingMode: 'user' }) }, audio: false };
}

/** La sensibilité : un geste plus PETIT fait le même effet, la main reste près du centre. Elle ne
 *  touche pas au pointeur, qui suit la main telle qu'elle est. */
export function scaleGesture(out, sensitivity) {
  const k = sensitivity || 1;
  return { ...out,
    rotate: out.rotate ? { dx: out.rotate.dx * k, dy: out.rotate.dy * k } : null,
    zoom: out.zoom ? Math.pow(out.zoom, k) : null };
}

/**
 * Allume les mains dans `box` (la vignette de la scène). `wasm` : dossier des moteurs ;
 * `model` : adresse du modèle ; `manage` : page où l'installer ; `onGesture(out, hands)` : chaque
 * image, avec les mains repérées (pour les dessiner). Rend `{stop}`.
 */
export async function startHands(box, { wasm, model, manage, onGesture, onError }) {
  const status = box.querySelector('.wc-hands-status');
  const say = (text, isError = false) => { status.innerHTML = text; box.classList.toggle('error', isError); };
  const fail = html => { say(html, true); if (onError) onError(); return { stop() {} }; };
  say(STATUS.loading);
  // L'accès à la caméra (contexte sécurisé, refus expliqué, repli, zoom, pistes rendues) : brique
  // commune `WamaCapture`, montée par base.html.
  const capture = window.WamaCapture;
  if (!capture.available()) return fail(capture.explain({ reason: 'insecure' }, 'camera'));
  const head = await fetch(model, { method: 'HEAD', credentials: 'same-origin' }).catch(() => null);
  if (!head || !head.ok) {
    return fail(`Le modèle des gestes n'est pas installé. <a href="${manage}">Gestion des modèles</a> → « MediaPipe Gesture Recognizer ».`);
  }
  const settings = loadSettings();
  const video = box.querySelector('video'), canvas = box.querySelector('canvas'), g = canvas.getContext('2d');
  let stream = null;
  // Le zoom MATÉRIEL, quand la caméra l'expose : au plus large par défaut.
  const applyZoom = () => capture.setZoom(stream, settings.zoom);
  // Ouvrir (ou rouvrir) la caméra selon les réglages ; une caméra choisie qui a disparu → celle par
  // défaut, et le choix est oublié.
  async function openCamera() {
    capture.close(stream);
    stream = await capture.open(cameraConstraints(settings), {
      fallback: true, onFallback: () => { settings.deviceId = ''; saveSettings(settings); } });
    video.srcObject = stream;
    await video.play().catch(() => {});
    await applyZoom();
  }
  try { await openCamera(); }
  catch (e) { return fail(capture.explain(e, 'camera')); }

  // ── Les réglages, dans la vignette (⚙) ──
  const gear = document.createElement('button');
  gear.type = 'button'; gear.className = 'wc-hands-gear'; gear.title = 'Réglages de la caméra';
  gear.innerHTML = '<i class="fas fa-gear"></i>';
  const panel = document.createElement('div');
  panel.className = 'wc-hands-settings'; panel.hidden = true;
  box.append(gear, panel);
  async function renderSettings() {
    if (panel.hidden) return;
    const cams = await capture.devices('camera');
    const st = capture.trackSettings(stream, 'camera'), z = capture.zoomRange(stream);
    const current = settings.deviceId || st.deviceId || '';
    const opt = (v, label, on) => { const o = document.createElement('option'); o.value = v; o.textContent = label; o.selected = on; return o.outerHTML; };
    panel.innerHTML =
      `<label>Caméra<select data-k="deviceId">${cams.map(c => opt(c.deviceId, c.label, c.deviceId === current)).join('')}</select></label>` +
      `<label>Champ<select data-k="wide">${opt('1', 'Large (16:9)', settings.wide)}${opt('0', 'Standard (4:3)', !settings.wide)}</select></label>` +
      (z ? `<label>Zoom de la caméra<input type="range" data-k="zoom" min="${z.min}" max="${z.max}" step="${z.step || 0.1}" value="${settings.zoom ?? z.min}"></label>` : '') +
      `<label>Sensibilité <output>${settings.sensitivity.toFixed(1)}</output><input type="range" data-k="sensitivity" min="0.5" max="4" step="0.1" value="${settings.sensitivity}"></label>` +
      `<p class="mute">${st.width && st.height ? `Image reçue : ${st.width} × ${st.height}` : ''}${z ? '' : ' · zoom non réglable sur cette caméra'}</p>`;
    panel.querySelectorAll('[data-k]').forEach(el => el.addEventListener(el.type === 'range' ? 'input' : 'change', async () => {
      const k = el.dataset.k;
      if (k === 'deviceId') { settings.deviceId = el.value; saveSettings(settings); await openCamera(); renderSettings(); }
      else if (k === 'wide') { settings.wide = el.value === '1'; saveSettings(settings); await openCamera(); renderSettings(); }
      else if (k === 'zoom') { settings.zoom = parseFloat(el.value); saveSettings(settings); await applyZoom(); }
      else if (k === 'sensitivity') {
        settings.sensitivity = parseFloat(el.value); saveSettings(settings);
        el.parentElement.querySelector('output').textContent = settings.sensitivity.toFixed(1);
      }
    }));
  }
  gear.addEventListener('click', () => { panel.hidden = !panel.hidden; renderSettings(); });

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
  const cleanup = () => {
    gear.remove(); panel.remove();
    capture.close(stream);
    video.srcObject = null;
    console.error = consoleError; window.fetch = pageFetch;
  };
  let recognizer;
  try {
    const { FilesetResolver, GestureRecognizer } = await import('mediapipe/tasks-vision');
    const fileset = await FilesetResolver.forVisionTasks(wasm);
    const make = delegate => GestureRecognizer.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: model, delegate }, runningMode: 'VIDEO', numHands: 2 });
    recognizer = await make('GPU').catch(() => make('CPU'));
  } catch (e) {
    cleanup();
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
    const dot = Math.max(3, canvas.width / 200);
    for (const h of hands) {
      g.fillStyle = h.gesture === FIST ? ink.fist : ink.open;
      for (const p of h.landmarks) { g.beginPath(); g.arc(p.x * canvas.width, p.y * canvas.height, dot, 0, 6.283); g.fill(); }
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
      onGesture(scaleGesture(out, settings.sensitivity), hands);
    }
    raf = requestAnimationFrame(loop);
  };
  raf = requestAnimationFrame(loop);
  return {
    stop() {
      running = false; cancelAnimationFrame(raf);
      try { recognizer.close(); } catch (e) { /* déjà fermé */ }
      cleanup();
      onGesture({ mode: 'none', rotate: null, zoom: null, pointer: null, click: false }, []);
    },
  };
}
