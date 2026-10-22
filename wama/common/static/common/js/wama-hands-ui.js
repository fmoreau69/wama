/* ==========================================================================
   WAMA — l'interface GLOBALE des mains (2026-10-22, décision de Fabien : « faire un composant
   commun global […] préparer la petite interface qui permettra de gérer tout ça de façon globale et
   universelle dans WAMA, même si pour le moment ça ne s'applique qu'aux scènes 3D — il vaut mieux
   déjà centraliser qu'ajouter des boutons dans toutes les scènes »).

   UNE icône dans la barre du haut (`includes/header.html`, `#wamaHandsToggle`), UNE vignette de
   caméra (avec ses réglages), UNE couche de MAINS VIRTUELLES sur toute la page, pour toute page de
   WAMA. Le moteur est `wama-hands.js` (gestes, caméra), chargé seulement à l'allumage.

   Ce qui est UNIVERSEL : le pointeur (bout de l'index) et le pincement, qui clique l'élément sous
   lui — un bouton, un lien, une puce, une ligne… Ce qui est PROPRE à une page, elle le DÉCLARE en
   cible (`registerHandTarget`) : la rotation (un poing), le zoom (deux poings), et ce que veut dire
   un clic ou un survol sur sa surface (une toile 3D choisit l'étoile sous le doigt). Pour l'instant
   seules les scènes 3D se déclarent : l'icône n'apparaît que sur une page qui a une cible.
   ========================================================================== */

const targets = new Set();
let engine = null, session = null, box = null, overlay = null, og = null;

const toggle = () => document.getElementById('wamaHandsToggle');

/**
 * Une page déclare ce qu'elle sait faire des gestes. `target` : `{element, rotate(dx, dy),
 * zoom(factor), click(clientX, clientY), hover(clientX, clientY)}` — tout est facultatif ; `element`
 * est la surface (une toile) où `click` et `hover` s'appliquent. Rend la fonction qui la retire.
 */
export function registerHandTarget(target) {
  targets.add(target);
  const btn = toggle();
  if (btn) { btn.closest('li')?.removeAttribute('hidden'); btn.hidden = false; }
  return () => {
    targets.delete(target);
    if (!targets.size) { stop(); if (btn) btn.closest('li')?.setAttribute('hidden', ''); }
  };
}

function ensureDom() {
  if (box) return;
  // La feuille du composant, à côté de lui (`common/css/wama-hands.css`) : chargée avec lui seulement.
  const link = document.createElement('link');
  link.rel = 'stylesheet'; link.href = new URL('../css/wama-hands.css', import.meta.url).href;
  document.head.appendChild(link);
  box = document.createElement('div');
  box.className = 'wama-hands'; box.hidden = true;
  box.innerHTML = '<video muted playsinline></video><canvas></canvas><div class="wc-hands-status"></div>';
  overlay = document.createElement('canvas');
  overlay.className = 'wama-hands-overlay'; overlay.hidden = true;
  document.body.append(overlay, box);
  og = overlay.getContext('2d');
}

const ink = () => {
  const s = getComputedStyle(box);
  return { line: s.getPropertyValue('--wama-hands-ink').trim(), fist: s.getPropertyValue('--wama-hands-grip').trim() };
};

// Les mains virtuelles : l'image de la caméra couvre toute la fenêtre, en miroir.
function drawHands(out, seen) {
  if (!engine || !og) return;
  overlay.width = innerWidth; overlay.height = innerHeight;
  og.clearRect(0, 0, overlay.width, overlay.height);
  const c = ink();
  for (const h of seen) {
    const pts = h.landmarks.map(p => { const s = engine.toScene(p); return [s.x * overlay.width, s.y * overlay.height]; });
    og.strokeStyle = og.fillStyle = h.gesture === 'Closed_Fist' ? c.fist : c.line;
    og.globalAlpha = 0.55; og.lineWidth = 3; og.lineCap = 'round';
    og.beginPath();
    for (const [a, b] of engine.HAND_BONES) { og.moveTo(...pts[a]); og.lineTo(...pts[b]); }
    og.stroke();
    og.globalAlpha = 0.8;
    for (const [x, y] of pts) { og.beginPath(); og.arc(x, y, 3.5, 0, 6.283); og.fill(); }
  }
  if (out.pointer) {
    const x = out.pointer.x * overlay.width, y = out.pointer.y * overlay.height;
    og.globalAlpha = 1; og.lineWidth = 2; og.strokeStyle = og.fillStyle = c.fist;
    og.beginPath(); og.arc(x, y, out.mode === 'pinch' ? 7 : 12, 0, 6.283); og.stroke();
    if (out.mode === 'pinch') og.fill();
  }
  og.globalAlpha = 1;
}

// Le pointeur : survol et clic de ce qui est SOUS lui (la couche des mains ne capte rien).
function point(out) {
  if (!out.pointer) return;
  const clientX = out.pointer.x * innerWidth, clientY = out.pointer.y * innerHeight;
  const el = document.elementFromPoint(clientX, clientY);
  if (!el) return;
  const surface = [...targets].find(t => t.element && (t.element === el || t.element.contains(el)));
  if (surface && surface.hover) surface.hover(clientX, clientY);
  if (!out.click) return;
  if (surface && surface.click) { surface.click(clientX, clientY); return; }
  const target = el.closest('button, a, summary, select, input, label, [role="button"], [data-goto], [data-filter], [data-group], .wc-label');
  if (!target) return;
  if (target.matches('input, select')) target.focus();
  target.click();
}

function onGesture(out, seen) {
  for (const t of targets) {
    if (out.rotate && t.rotate) t.rotate(out.rotate.dx, out.rotate.dy);
    if (out.zoom && t.zoom) t.zoom(out.zoom);
  }
  drawHands(out, seen);
  point(out);
}

/** Le point d'entrée des gestes — celui de la caméra, exporté pour qu'un essai (scénario nocturne)
 *  rejoue un geste sans main devant l'objectif : `applyGesture({pointer: {x, y}, click: true})`. */
export function applyGesture(out, seen = []) {
  ensureDom();
  onGesture({ mode: 'none', rotate: null, zoom: null, pointer: null, click: false, ...out }, seen);
}

function setOn(on) {
  const btn = toggle();
  if (!btn) return;
  btn.classList.toggle('active', on);
  btn.setAttribute('aria-pressed', on ? 'true' : 'false');
}

export function stop() {
  if (!session) return;
  session.stop(); session = null;
  if (box) box.hidden = true;
  if (overlay) overlay.hidden = true;
  for (const t of targets) if (t.release) t.release();
  setOn(false);
}

export async function start() {
  if (session) return;
  const btn = toggle();
  ensureDom();
  box.hidden = false; overlay.hidden = false; setOn(true);
  engine = engine || await import('wama/hands');
  // Le dossier des moteurs WebAssembly se DÉDUIT de l'importmap (`mediapipe/tasks-vision` y est
  // déclaré une fois) : aucune version recopiée ici.
  const wasm = new URL('./wasm', import.meta.resolve('mediapipe/tasks-vision')).href;
  session = await engine.startHands(box, {
    wasm, model: btn.dataset.handsModel, manage: btn.dataset.handsManage, onGesture,
    onError: () => { setOn(false); overlay.hidden = true; },
  });
  for (const t of targets) if (t.grab) t.grab();
}

// L'icône de la barre : allumer, éteindre.
function bind() {
  const btn = toggle();
  if (!btn || btn.dataset.bound) return;
  btn.dataset.bound = '1';
  btn.addEventListener('click', () => (session ? stop() : start()));
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind); else bind();
addEventListener('pagehide', stop);
