/* ==========================================================================
   WAMA — scènes 3D de la présentation (three.js vendorisé, importmap commune
   `common/_three_importmap.html` — aucun CDN).

   Une scène s'accroche au `.scene-slot[data-scene]` de la frame active, une
   fois la caméra arrivée (événement 'wama:step', settled=true) :
     - `worlds` : les quatre mondes — Médias + Data → Lab, sur le socle Transversal ;
     - `access` : TOUS les cas du modèle d'accès (tier × rôles × app), décidés
                  côté serveur par `accounts.permissions.accessible()`.
   ========================================================================== */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const layer = document.getElementById('scene-layer');
const tooltip = document.getElementById('scene-tooltip');
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

let renderer = null;
try {
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
} catch (e) {
  console.warn('[présentation] WebGL indisponible — scènes 3D désactivées', e);
}
if (renderer) {
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.setClearColor(0x000000, 0);
  layer.appendChild(renderer.domElement);
}

const COLORS = { media: 0x38e1ff, data: 0xfbbf24, lab: 0xf472b6, trans: 0x8b7bff };
const scenes = {};
let active = null, activeSlot = null, raf = null;

// ── Utilitaires ──────────────────────────────────────────────────────────
function glowTexture() {
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grd.addColorStop(0, 'rgba(255,255,255,1)');
  grd.addColorStop(0.25, 'rgba(255,255,255,.45)');
  grd.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}
const GLOW = glowTexture();

function makeLabel(container, html, cls = '') {
  const d = document.createElement('div');
  d.className = 'scene-label ' + cls; d.innerHTML = html; container.appendChild(d);
  return d;
}
function projectLabels(sc) {
  const w = layer.clientWidth, h = layer.clientHeight, v = new THREE.Vector3();
  for (const l of sc.labels) {
    l.obj.getWorldPosition(v); if (l.offset) v.add(l.offset);
    v.project(sc.camera);
    const hidden = v.z > 1;
    l.el.style.display = hidden ? 'none' : '';
    l.el.style.left = ((v.x + 1) / 2 * w) + 'px';
    l.el.style.top = ((1 - v.y) / 2 * h) + 'px';
  }
}
function pointer(ev) {
  const r = layer.getBoundingClientRect();
  return new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
}
function showTip(ev, html) {
  if (!html) { tooltip.style.display = 'none'; return; }
  tooltip.innerHTML = html; tooltip.style.display = 'block';
  const r = layer.getBoundingClientRect();
  tooltip.style.left = Math.min(ev.clientX - r.left + 14, r.width - 290) + 'px';
  tooltip.style.top = (ev.clientY - r.top + 14) + 'px';
}

// ── Scène 1 : les quatre mondes ──────────────────────────────────────────
function buildWorlds() {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 200);
  camera.position.set(0, 5.2, 14.5);
  const labelsBox = document.createElement('div'); labelsBox.style.cssText = 'position:absolute;inset:0;pointer-events:none';
  layer.appendChild(labelsBox);
  const controls = new OrbitControls(camera, renderer.domElement);
  Object.assign(controls, { enableDamping: true, enablePan: false, minDistance: 7, maxDistance: 24,
                            autoRotate: !reduceMotion, autoRotateSpeed: 0.55, maxPolarAngle: Math.PI * 0.62 });
  controls.target.set(0, 0.2, 0);
  const labels = [], pickables = [], anims = [];

  // Socle Transversal : disque polaire + anneaux.
  const base = new THREE.Group(); base.position.y = -1.7; scene.add(base);
  const grid = new THREE.PolarGridHelper(6, 16, 6, 96, COLORS.trans, 0x2a2f5a);
  grid.material.transparent = true; grid.material.opacity = 0.55; base.add(grid);
  const disc = new THREE.Mesh(new THREE.CircleGeometry(6, 96),
    new THREE.MeshBasicMaterial({ color: COLORS.trans, transparent: true, opacity: 0.06, side: THREE.DoubleSide }));
  disc.rotation.x = -Math.PI / 2; base.add(disc);
  for (const [r, o] of [[6, .9], [4.2, .45], [2.2, .35]]) {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(r, 0.012, 8, 160),
      new THREE.MeshBasicMaterial({ color: COLORS.trans, transparent: true, opacity: o }));
    ring.rotation.x = Math.PI / 2; base.add(ring);
  }
  const core = new THREE.Mesh(new THREE.SphereGeometry(0.34, 32, 16), new THREE.MeshBasicMaterial({ color: COLORS.trans }));
  base.add(core);
  const coreGlow = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, color: COLORS.trans, blending: THREE.AdditiveBlending, depthWrite: false }));
  coreGlow.scale.set(3, 3, 1); base.add(coreGlow);
  core.userData.target = 'transversal'; pickables.push(core);
  labels.push({ obj: core, el: makeLabel(labelsBox, 'Transversal<small>le substrat commun</small>'), offset: new THREE.Vector3(0, -0.75, 0) });

  // Satellites du substrat, en orbite sur l'anneau extérieur.
  const sats = ['Studio', 'Médiathèque', 'Registres', 'Manifestes', 'Assistant · LLM', 'Gouverneur', 'Mémoire · RAG', 'Model manager', 'Docs · tests'];
  const satGroup = new THREE.Group(); base.add(satGroup);
  sats.forEach((name, i) => {
    const a = (i / sats.length) * Math.PI * 2;
    const m = new THREE.Mesh(new THREE.OctahedronGeometry(0.13), new THREE.MeshBasicMaterial({ color: 0xc9c2ff }));
    m.position.set(Math.cos(a) * 4.2, 0.05, Math.sin(a) * 4.2); satGroup.add(m);
    labels.push({ obj: m, el: makeLabel(labelsBox, name, 'minor'), offset: new THREE.Vector3(0, 0.32, 0) });
  });
  anims.push(t => { satGroup.rotation.y = t * 0.00006; core.scale.setScalar(1 + 0.06 * Math.sin(t / 600)); });

  // Les trois mondes-pairs.
  const worlds = [
    { id: 'media', name: 'Médias', sub: '10 apps · média → média', pos: [-3.6, 1.5, 2.6], color: COLORS.media },
    { id: 'data', name: 'Data', sub: 'données → traitement → données', pos: [-2.6, 0.9, -3.0], color: COLORS.data },
    { id: 'lab', name: 'Lab', sub: 'recherche métier', pos: [3.4, 1.6, 0.0], color: COLORS.lab },
  ];
  const nodes = {};
  for (const w of worlds) {
    const g = new THREE.Group(); g.position.set(...w.pos); scene.add(g);
    const inner = new THREE.Mesh(new THREE.SphereGeometry(0.55, 40, 20),
      new THREE.MeshBasicMaterial({ color: w.color, transparent: true, opacity: 0.85 }));
    const shell = new THREE.Mesh(new THREE.IcosahedronGeometry(0.95, 1),
      new THREE.MeshBasicMaterial({ color: w.color, wireframe: true, transparent: true, opacity: 0.35 }));
    const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, color: w.color, blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0.9 }));
    glow.scale.set(3.6, 3.6, 1);
    g.add(inner, shell, glow);
    inner.userData.target = w.id; shell.userData.target = w.id; pickables.push(inner, shell);
    labels.push({ obj: g, el: makeLabel(labelsBox, `${w.name}<small>${w.sub}</small>`), offset: new THREE.Vector3(0, 1.35, 0), target: w.id });
    // Faisceau vers le socle : chaque monde s'appuie sur le substrat.
    const beamGeo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(...w.pos), new THREE.Vector3(w.pos[0] * 0.62, -1.7, w.pos[2] * 0.62)]);
    scene.add(new THREE.Line(beamGeo, new THREE.LineDashedMaterial({ color: w.color, dashSize: 0.12, gapSize: 0.1, transparent: true, opacity: 0.5 })).computeLineDistances());
    const phase = Math.random() * 6;
    anims.push(t => { shell.rotation.y = t * 0.0004 + phase; shell.rotation.x = t * 0.00023; g.position.y = w.pos[1] + 0.12 * Math.sin(t / 900 + phase); });
    nodes[w.id] = g;
  }

  // Flux Médias → Lab et Data → Lab : particules le long d'arcs.
  function stream(from, to, color) {
    const a = new THREE.Vector3(...from), b = new THREE.Vector3(...to);
    const mid = a.clone().lerp(b, 0.5).add(new THREE.Vector3(0, 1.8, 0));
    const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
    const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 64, 0.012, 6, false),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.35 }));
    scene.add(tube);
    const N = 26, pos = new Float32Array(N * 3);
    const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    const pts = new THREE.Points(geo, new THREE.PointsMaterial({ color, size: 0.11, map: GLOW, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
    scene.add(pts);
    const v = new THREE.Vector3();
    anims.push(t => {
      for (let i = 0; i < N; i++) {
        curve.getPoint(((t / 4200) + i / N) % 1, v); pos.set([v.x, v.y, v.z], i * 3);
      }
      geo.attributes.position.needsUpdate = true;
    });
  }
  stream(worlds[0].pos, worlds[2].pos, COLORS.media);
  stream(worlds[1].pos, worlds[2].pos, COLORS.data);
  // Glu inter-mondes : Médias ↔ Data (capacités et ports typés).
  stream(worlds[1].pos, worlds[0].pos, 0x9fb4ff);

  // Interaction : survol + clic → la présentation plonge dans le monde.
  const ray = new THREE.Raycaster();
  function pick(ev) { ray.setFromCamera(pointer(ev), camera); return ray.intersectObjects(pickables)[0]; }
  const onMove = ev => { const h = pick(ev); renderer.domElement.style.cursor = h ? 'pointer' : 'grab'; };
  const onClick = ev => { const h = pick(ev); if (h && window.WamaPrez) window.WamaPrez.goId(h.object.userData.target); };
  labels.forEach(l => {
    const tgt = l.target || (l.obj.userData && l.obj.userData.target);
    if (tgt) l.el.addEventListener('click', () => window.WamaPrez && window.WamaPrez.goId(tgt));
  });

  return { scene, camera, controls, labels, labelsBox, anims,
           listeners: { pointermove: onMove, click: onClick } };
}

// ── Scène 2 : les droits, tous les cas ───────────────────────────────────
const TIER_COLORS = [0x94a3b8, COLORS.media, COLORS.data, COLORS.lab];
const APP_LABELS = { media_library: 'Médiathèque', model_manager: 'Model manager', face_analyzer: 'Face Analyzer', cam_analyzer: 'Cam Analyzer' };
const appLabel = id => APP_LABELS[id] || id.charAt(0).toUpperCase() + id.slice(1);

function buildAccess(slot) {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 400);
  camera.position.set(12, 30, 40);
  const labelsBox = document.createElement('div'); labelsBox.style.cssText = 'position:absolute;inset:0;pointer-events:none';
  layer.appendChild(labelsBox);
  const controls = new OrbitControls(camera, renderer.domElement);
  Object.assign(controls, { enableDamping: true, enablePan: false, minDistance: 14, maxDistance: 70,
                            autoRotate: !reduceMotion, autoRotateSpeed: 0.35 });
  const sc = { scene, camera, controls, labels: [], labelsBox, anims: [], listeners: {}, ready: false };
  const panel = document.getElementById('access-panel');
  sc.panel = panel;

  fetch(slot.dataset.src, { credentials: 'same-origin' })
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(data => populate(sc, data))
    .catch(err => {
      panel.querySelector('.result').innerHTML = `<em>Cas d'accès indisponibles (${err.message}).</em>`;
    });
  return sc;
}

function populate(sc, data) {
  const { scene, camera, controls } = sc;
  const nA = data.apps.length, nR = data.role_sets.length, nT = data.tiers.length;
  const DX = 1.15, DZ = 1.0, DY = 2.6;
  const ox = -(nA - 1) * DX / 2, oz = -(nR - 1) * DZ / 2, oy = -(nT - 1) * DY / 2;
  const count = nA * nR * nT;
  const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(0.72, 0.36, 0.72), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.95 }), count);
  const dummy = new THREE.Object3D(), col = new THREE.Color();
  const idx = [];     // instanceId → [tier, roleSet, app]
  let k = 0;
  for (let t = 0; t < nT; t++) for (let r = 0; r < nR; r++) for (let a = 0; a < nA; a++) {
    dummy.position.set(ox + a * DX, oy + t * DY, oz + r * DZ);
    dummy.scale.setScalar(data.matrix[t][r][a] ? 1 : 0.28);
    dummy.updateMatrix(); mesh.setMatrixAt(k, dummy.matrix); idx.push([t, r, a]); k++;
  }
  scene.add(mesh);

  // Plateaux par tier + étiquettes.
  for (let t = 0; t < nT; t++) {
    const plate = new THREE.Mesh(new THREE.PlaneGeometry(nA * DX + 0.8, nR * DZ + 0.8),
      new THREE.MeshBasicMaterial({ color: TIER_COLORS[t], transparent: true, opacity: 0.05, side: THREE.DoubleSide, depthWrite: false }));
    plate.rotation.x = -Math.PI / 2; plate.position.y = oy + t * DY - 0.25; scene.add(plate);
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(plate.geometry),
      new THREE.LineBasicMaterial({ color: TIER_COLORS[t], transparent: true, opacity: 0.45 }));
    edges.rotation.x = -Math.PI / 2; edges.position.copy(plate.position); scene.add(edges);
    const anchor = new THREE.Object3D(); anchor.position.set(ox - 1.2, plate.position.y, oz - 1.4); scene.add(anchor);
    sc.labels.push({ obj: anchor, el: makeLabel(sc.labelsBox, data.tiers[t].label, 'minor') });
  }
  // Noms d'apps au pied de la pile.
  for (let a = 0; a < nA; a++) {
    const anchor = new THREE.Object3D(); anchor.position.set(ox + a * DX, oy - 1.0, oz + (nR - 1) * DZ + 1.1); scene.add(anchor);
    const el = makeLabel(sc.labelsBox, appLabel(data.apps[a].id), 'minor');
    el.style.transform = 'translate(-100%, -50%) rotate(-50deg)'; el.style.transformOrigin = '100% 50%';
    sc.labels.push({ obj: anchor, el });
  }
  controls.target.set(5, -2.5, 1);

  // Repère de la rangée sélectionnée : un cadre lumineux autour des 15 décisions du cas.
  const marker = new THREE.Mesh(new THREE.BoxGeometry(nA * DX + 0.3, 0.7, DZ * 0.95),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.10, depthWrite: false }));
  const markerEdges = new THREE.LineSegments(new THREE.EdgesGeometry(marker.geometry),
    new THREE.LineBasicMaterial({ color: 0xffffff }));
  marker.add(markerEdges); marker.visible = false; scene.add(marker);
  sc.anims.push(t => { markerEdges.material.opacity = 0.6 + 0.4 * Math.sin(t / 250); markerEdges.material.transparent = true; });

  // Couleurs selon la sélection (tier, jeu de rôles) — null = tout.
  let sel = { t: null, r: null };
  function paint() {
    marker.visible = sel.t !== null && sel.r !== null;
    if (marker.visible) marker.position.set(ox + (nA - 1) * DX / 2, oy + sel.t * DY, oz + sel.r * DZ);
    for (let i = 0; i < count; i++) {
      const [t, r, a] = idx[i], on = data.matrix[t][r][a];
      const focus = (sel.t === null || sel.t === t) && (sel.r === null || sel.r === r);
      col.setHex(on ? TIER_COLORS[t] : 0x39405a);
      col.multiplyScalar(focus ? 1 : 0.1);
      mesh.setColorAt(i, col);
    }
    mesh.instanceColor.needsUpdate = true;
    describe();
  }

  const panel = sc.panel;
  const roleKeys = data.roles.map(r => r.key);
  let roles = new Set();
  const rsIndex = () => data.role_sets.findIndex(s => s.length === roles.size && s.every(x => roles.has(x)));
  panel.querySelector('.stats-line').innerHTML =
    `<b>${data.configurations}</b> configurations (${nT} profils × ${nR} jeux de rôles) × <b>${nA}</b> apps` +
    ` = <b>${data.configurations * nA}</b> décisions · <b>${data.distinct_rows}</b> comportements distincts`;
  const tierBox = panel.querySelector('.tiers'), roleBox = panel.querySelector('.roles');
  tierBox.innerHTML = ''; roleBox.innerHTML = '';
  const allChip = document.createElement('span'); allChip.className = 'chip on'; allChip.textContent = 'Tous';
  tierBox.appendChild(allChip);
  const tierChips = data.tiers.map((t, i) => {
    const c = document.createElement('span'); c.className = `chip t${i}`; c.textContent = t.label; tierBox.appendChild(c); return c;
  });
  const roleChips = data.roles.map(r => {
    const c = document.createElement('span'); c.className = 'chip'; c.textContent = r.label; c.title = r.help; roleBox.appendChild(c); return c;
  });
  function sync() {
    allChip.classList.toggle('on', sel.t === null);
    tierChips.forEach((c, i) => c.classList.toggle('on', sel.t === i));
    roleChips.forEach((c, i) => c.classList.toggle('on', roles.has(roleKeys[i])));
    paint();
  }
  allChip.onclick = () => { stopTour(); sel = { t: null, r: null }; roles = new Set(); sync(); };
  tierChips.forEach((c, i) => c.onclick = () => { stopTour(); sel.t = i; sel.r = rsIndex(); sync(); });
  roleChips.forEach((c, i) => c.onclick = () => {
    stopTour(); const key = roleKeys[i]; roles.has(key) ? roles.delete(key) : roles.add(key);
    if (sel.t === null) sel.t = 1; sel.r = rsIndex(); sync();
  });

  function describe() {
    const out = panel.querySelector('.result');
    if (sel.t === null || sel.r === null) {
      out.innerHTML = '<em>Choisissez un profil et des rôles, ou lancez le parcours : chaque plateau est un profil, chaque rangée un jeu de rôles, chaque colonne une app.</em>';
      return;
    }
    const row = data.matrix[sel.t][sel.r];
    const apps = data.apps.filter((_, a) => row[a]).map(a => appLabel(a.id));
    const rs = data.role_sets[sel.r].map(k => data.roles.find(r => r.key === k).label);
    out.innerHTML = `<b>${data.tiers[sel.t].label}</b> · ${rs.length ? rs.join(' + ') : 'aucun rôle'}<br>` +
      `→ <b>${apps.length}/${nA}</b> apps${apps.length ? ' : ' + apps.join(', ') : ''}`;
  }

  // Parcours automatique de tous les cas.
  let tour = null, tourI = 0;
  function stopTour() { if (tour) { clearInterval(tour); tour = null; panel.querySelector('.btn-tour').textContent = '▶ Parcourir tous les cas'; } }
  panel.querySelector('.btn-tour').onclick = () => {
    if (tour) { stopTour(); return; }
    panel.querySelector('.btn-tour').textContent = '⏸ Pause';
    const stepTour = () => {
      const t = Math.floor(tourI / nR) % nT, r = tourI % nR;
      sel = { t, r }; roles = new Set(data.role_sets[r]); sync(); tourI++;
    };
    stepTour(); tour = setInterval(stepTour, 1100);
  };
  panel.querySelector('.btn-all').onclick = () => allChip.onclick();
  sc.stopTour = stopTour;

  // Survol : détail de la cellule.
  const ray = new THREE.Raycaster();
  sc.listeners.pointermove = ev => {
    ray.setFromCamera(pointer(ev), camera);
    const h = ray.intersectObject(mesh)[0];
    if (!h) { showTip(ev, null); return; }
    const [t, r, a] = idx[h.instanceId], app = data.apps[a];
    const rs = data.role_sets[r].map(k => data.roles.find(x => x.key === k).label);
    const pol = app.min_tier ? `profil min. ${app.min_tier}` : '';
    const need = app.roles.length ? `rôles ouvrant l'accès : ${app.roles.join(', ')}` : 'app commune (tout compte)';
    showTip(ev, `<b>${appLabel(app.id)}</b> — ${data.matrix[t][r][a] ? '<span style="color:#34d399">accès</span>' : '<span style="color:#f87171">refus</span>'}<br>` +
      `${data.tiers[t].label} · ${rs.length ? rs.join(' + ') : 'aucun rôle'}<br><span style="color:#8a94b0">${need}${pol ? ' · ' + pol : ''}</span>`);
  };
  sc.listeners.pointerleave = ev => showTip(ev, null);
  paint(); sc.ready = true;
}

// ── Cycle de vie : accrochage à la frame active ─────────────────────────
function placeLayer(slot) {
  const r = slot.getBoundingClientRect();
  Object.assign(layer.style, { left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px' });
  renderer.setSize(r.width, r.height, false);
  renderer.domElement.style.width = '100%'; renderer.domElement.style.height = '100%';
  if (active) { active.camera.aspect = r.width / Math.max(1, r.height); active.camera.updateProjectionMatrix(); }
  const panel = document.getElementById('access-panel');
  if (active && active.panel) {
    Object.assign(panel.style, { left: (r.right - 346) + 'px', top: (r.top + 16) + 'px' });
  }
}
function detach() {
  if (!active) return;
  active.controls.enabled = false;
  for (const [ev, fn] of Object.entries(active.listeners)) renderer.domElement.removeEventListener(ev, fn);
  active.labelsBox.style.display = 'none';
  if (active.panel) active.panel.classList.remove('on');
  if (active.stopTour) active.stopTour();
  tooltip.style.display = 'none';
  active = null; activeSlot = null;
  layer.classList.remove('on');
  if (raf) { cancelAnimationFrame(raf); raf = null; }
}
function attach(slot) {
  const name = slot.dataset.scene;
  if (!scenes[name]) scenes[name] = name === 'worlds' ? buildWorlds() : buildAccess(slot);
  active = scenes[name]; activeSlot = slot;
  active.controls.enabled = true;
  for (const [ev, fn] of Object.entries(active.listeners)) renderer.domElement.addEventListener(ev, fn);
  active.labelsBox.style.display = '';
  if (active.panel) active.panel.classList.add('on');
  placeLayer(slot);
  layer.classList.add('on');
  const loop = now => {
    if (!active) return;
    active.anims.forEach(f => f(now));
    active.controls.update();
    renderer.render(active.scene, active.camera);
    projectLabels(active);
    raf = requestAnimationFrame(loop);
  };
  raf = requestAnimationFrame(loop);
}

if (renderer) {
  document.addEventListener('wama:step', e => {
    const { frame, settled } = e.detail;
    const slot = frame && frame.querySelector('.scene-slot[data-scene]');
    if (!settled || !slot) { detach(); return; }
    if (activeSlot === slot) { placeLayer(slot); return; }
    detach(); attach(slot);
  });
  // Le moteur a pu émettre avant le chargement de ce module (import différé) : rattrapage.
  const f = document.querySelector('.frame.active');
  if (f && !document.body.classList.contains('moving')) {
    const slot = f.querySelector('.scene-slot[data-scene]'); if (slot) attach(slot);
  }
} else {
  document.querySelectorAll('.scene-slot').forEach(s => {
    s.innerHTML = '<p style="padding:40px;font-size:22px;color:#6b7693">Scène 3D indisponible : WebGL n\'est pas actif dans ce navigateur.</p>';
  });
}
