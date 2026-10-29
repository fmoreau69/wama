/* ==========================================================================
   WAMA — la brique commune des CONSTELLATIONS (2026-10-21, demande de Fabien :
   « une brique commune réutilisable pour différents registres »).

   Une scène de proximité : des NŒUDS (étoiles), des GROUPES (sphères de verre qui enveloppent
   leurs membres), des LIENS orientés et comptés (arcs à particules), des FAISCEAUX vers un groupe
   ou vers le cœur, et des FACTEURS qui rapprochent deux nœuds, pondérés par des curseurs. La
   distance se calcule ici, à l'écran, parce que ses poids sont des curseurs ; les FAITS viennent de
   leur brique, côté serveur.

   Deux entrées :
     - la DÉCLARATION de la scène (`wama/common/scenes.py`), rendue par le gabarit commun
       `common/constellation.html` dans un `<script type="application/json">` de la scène :
       couches, facteurs, sortes de groupes, mesures, textes ;
     - les DONNÉES, lues à `data-src` : soit déjà au contrat (`{nodes, groups, links, beams,
       colorings}`), soit des faits qu'un ADAPTATEUR de la scène met au contrat (`adapt`).
   Une scène peut aussi fournir son volet (`hooks.detail`, `hooks.legend`, `hooks.tip`) ; sans
   eux, le volet se rend des SECTIONS déclarées sur chaque nœud (`node.detail`).

   Grammaire et cartographie : `docs/construction/ui/WAMA_SCENES_3D.md`. Premier consommateur : la
   constellation des utilisateurs (`accounts/js/user-constellation.js`), portée sans changement
   visible (banc de parité au pixel, 2026-10-21). Moteur : three.js vendorisé (importmap commune,
   aucun CDN), langage visuel de la scène des mondes (`presentation/wama-presentation-3d.js`).
   ========================================================================== */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

export const css = hex => '#' + hex.toString(16).padStart(6, '0');
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const initials = name => (String(name).match(/[\p{L}\p{N}]+/gu) || ['?']).slice(0, 2).map(w => w[0].toUpperCase()).join('');
export const fmtDate = iso => iso ? new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' }) : '—';
const plural = (n, one, many) => n > 1 ? many : one;

// Hasard DÉTERMINISTE (graine = identifiant du nœud) : la constellation garde sa forme d'une visite à l'autre.
export function rng(seed) {
  let a = (seed * 2654435761) >>> 0;
  return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
// Graine d'un identifiant qui n'est pas un nombre (une licence, une clé de modèle).
export function seedOf(id) {
  if (typeof id === 'number') return id;
  let h = 0;
  for (const ch of String(id)) h = (Math.imul(h, 31) + ch.codePointAt(0)) | 0;
  return Math.abs(h) % 100000;
}

function glowTexture() {
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grd.addColorStop(0, 'rgba(255,255,255,1)');
  grd.addColorStop(0.22, 'rgba(255,255,255,.5)');
  grd.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}

// Verre des sphères : un liseré lumineux (Fresnel) sur un cœur presque transparent.
function glassMaterial(color, base = 0.025, rim = 0.5) {
  return new THREE.ShaderMaterial({
    uniforms: { uColor: { value: new THREE.Color(color) }, uBase: { value: base }, uRim: { value: rim }, uFade: { value: 1 } },
    vertexShader: `varying vec3 vN; varying vec3 vV;
      void main() { vN = normalize(normalMatrix * normal); vec4 mv = modelViewMatrix * vec4(position, 1.0);
        vV = normalize(-mv.xyz); gl_Position = projectionMatrix * mv; }`,
    fragmentShader: `uniform vec3 uColor; uniform float uBase; uniform float uRim; uniform float uFade;
      varying vec3 vN; varying vec3 vV;
      void main() { float f = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), 2.6);
        gl_FragColor = vec4(uColor, (uBase + f * uRim) * uFade); }`,
    transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending,
  });
}

// Formes des satellites (ce qu'un nœud porte) — une par famille déclarée par la scène.
const SAT_SHAPES = {
  octa: () => new THREE.OctahedronGeometry(0.11),
  tetra: () => new THREE.TetrahedronGeometry(0.12),
  box: () => new THREE.BoxGeometry(0.13, 0.13, 0.13),
  torus: () => new THREE.TorusGeometry(0.07, 0.025, 6, 14),
  ico: () => new THREE.IcosahedronGeometry(0.11),
  dodeca: () => new THREE.DodecahedronGeometry(0.1),
};

// Les constantes de la mise en espace : celles de la constellation des utilisateurs. Une scène
// plus peuplée peut les ajuster (`spec.layout`).
const LAYOUT = { repulsion: 26, gap: 1.2, push: 0.6, spring: 0.045, springCap: 8, rest: 13, gravity: 0.012,
                 coreKeep: 3.8, coreKick: 0.4, damping: 0.82, maxSpeed: 1.2, cooling: 0.993, warmup: 260, idleAlpha: 0.25,
                 spread: 1, home: 36 };

/**
 * Monte une constellation dans `stage` (un `.wc-stage` du gabarit commun).
 * `adapt(data, api)` : met des faits au contrat (facultatif) ; `hooks` : `{tip, detail, legend}`.
 */
export function mountConstellation(stage, { adapt = null, hooks = {} } = {}) {
  const $ = sel => stage.querySelector(sel);
  const host = $('.wc-canvas');
  const labelsBox = $('.wc-labels');
  const tooltip = $('.wc-tooltip');
  const panel = $('.wc-panel');
  const statsLine = $('.wc-stats');
  const spec = JSON.parse(($('script[type="application/json"]') || {}).textContent || '{}');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const L = Object.assign({}, LAYOUT, spec.layout || {});

  // ── Palette : les JETONS de thème (`wama-constellation.css`, `--wc-*`), lus à l'ouverture —
  // jamais un hexadécimal recopié de la feuille. Une couleur se donne en jeton (`'--wc-share'`)
  // ou, pour une palette de DESSIN propre à la scène, en nombre.
  const tokens = new Map();
  function token(name, fallback = 0x64748b) {
    const v = getComputedStyle(stage).getPropertyValue(name).trim();
    try { return v ? new THREE.Color(v).getHex() : fallback; } catch (e) { return fallback; }
  }
  const color = v => {
    if (typeof v === 'number') return v;
    if (typeof v !== 'string' || !v.startsWith('--')) return 0x64748b;
    if (!tokens.has(v)) tokens.set(v, token(v));
    return tokens.get(v);
  };

  // ── Moteur ──────────────────────────────────────────────────────────
  let renderer = null;
  try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); } catch (e) { console.warn('[constellation] WebGL indisponible', e); }

  function fitStage() {
    // Sous la barre du haut, jusqu'en bas de la fenêtre : la barre a sa propre hauteur selon la largeur.
    const nav = document.querySelector('.top_nav');                 // absente en mode intégré
    const top = nav ? Math.max(0, nav.getBoundingClientRect().bottom) : 0;
    stage.style.top = top + 'px';
  }
  fitStage();

  if (!renderer) {
    statsLine.textContent = '';
    panel.innerHTML = '<p>La scène 3D demande WebGL, qui n\'est pas actif dans ce navigateur.</p>';
    return;
  }
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.setClearColor(0x000000, 0);
  host.appendChild(renderer.domElement);
  fetch(stage.dataset.src, { credentials: 'same-origin' })
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(data => start(adapt ? adapt(data, { color, spec }) : data, data))
    .catch(err => { statsLine.textContent = `Constellation indisponible (${err.message}).`; });

  function start(model, raw) {
    const layers = spec.layers || [];
    const layerOf = role => (layers.find(l => l.role === role) || {}).key;
    const linksLayer = layerOf('links'), satsLayer = layerOf('satellites'), namesLayer = layerOf('names');
    const kinds = spec.group_kinds || {};
    const factors = spec.factors || [];
    const colorings = model.colorings || {};
    const palettes = Object.fromEntries(Object.entries(colorings).map(([k, c]) =>
      [k, { pal: Object.fromEntries(Object.entries(c.palette || {}).map(([cat, v]) => [cat, color(v)])), fallback: color(c.fallback ?? 0x64748b) }]));
    const SHARE_COLOR = color('--wc-share'), CORE_COLOR = color('--wc-core'), FOG_COLOR = color('--wc-fog'), STARS_COLOR = color('--wc-stars');
    const GLOW = glowTexture();
    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(FOG_COLOR, 0.012);
    const camera = new THREE.PerspectiveCamera(48, 1, 0.1, 800);
    camera.position.set(0, 9, 34);
    const controls = new OrbitControls(camera, renderer.domElement);
    Object.assign(controls, { enableDamping: true, dampingFactor: 0.07, minDistance: 4, maxDistance: 140,
                              autoRotate: !reduceMotion, autoRotateSpeed: 0.25 });

    // ── Décor : champ d'étoiles lointaines + cœur « WAMA » au centre ───
    {
      const N = 1600, pos = new Float32Array(N * 3), r = rng(7);
      for (let i = 0; i < N; i++) {
        const u = r() * 2 - 1, th = r() * Math.PI * 2, d = 120 + r() * 220, s = Math.sqrt(1 - u * u);
        pos.set([d * s * Math.cos(th), d * u, d * s * Math.sin(th)], i * 3);
      }
      const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      scene.add(new THREE.Points(g, new THREE.PointsMaterial({ color: STARS_COLOR, size: 0.9, sizeAttenuation: true, transparent: true, opacity: 0.55, fog: false })));
    }
    const core = new THREE.Group(); scene.add(core);
    const coreMesh = new THREE.Mesh(new THREE.IcosahedronGeometry(0.45, 1), new THREE.MeshBasicMaterial({ color: CORE_COLOR, wireframe: true, transparent: true, opacity: 0.6 }));
    const coreGlow = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, color: CORE_COLOR, blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0.8 }));
    coreGlow.scale.set(3.4, 3.4, 1);
    core.add(coreMesh, coreGlow);
    const coreSpec = spec.core || { label: 'WAMA', sub: 'le système' };
    const coreLabel = label(`${esc(coreSpec.label)}<small>${esc(coreSpec.sub)}</small>`, 'core');

    // ── Index des groupes : arbres (`parent`) pour les sortes hiérarchiques ──
    const groupById = new Map(model.groups.map(g => [String(g.id), g]));
    const hierarchical = g => !!(kinds[g.kind] || {}).hierarchical;
    const depthCache = new Map();
    const depth = id => {
      id = String(id);
      if (depthCache.has(id)) return depthCache.get(id);
      let d = 0, n = groupById.get(id), guard = 0;
      while (n && n.parent != null && groupById.has(String(n.parent)) && guard++ < 20) { d++; n = groupById.get(String(n.parent)); }
      depthCache.set(id, d); return d;
    };
    const chain = id => {             // groupe → … → racine
      const out = []; let n = groupById.get(String(id)), guard = 0;
      while (n && guard++ < 20) { out.push(String(n.id)); n = n.parent != null ? groupById.get(String(n.parent)) : null; }
      return out;
    };
    const maxDepth = Math.max(0, ...model.groups.filter(hierarchical).map(g => depth(g.id)));
    const pairKey = (a, b) => String(a) < String(b) ? `${a}:${b}` : `${b}:${a}`;
    const pairCount = new Map();
    for (const l of model.links || []) pairCount.set(pairKey(l.from, l.to), (pairCount.get(pairKey(l.from, l.to)) || 0) + l.count);

    // ── Les étoiles ──────────────────────────────────────────────────────
    // Couches : leur état de départ est celui des puces du gabarit (`on`) ; la couche des NOMS
    // s'éteint d'office quand une présentation intègre la page (`data-embed`).
    const state = { colorBy: ((spec.colorings || [])[0] || {}).key,
                    layers: Object.fromEntries(layers.map(l => [l.key, stage.dataset.embed && l.embed_on !== undefined ? !!l.embed_on : !!l.on])),
                    weights: Object.fromEntries(factors.map(w => [w.key, w.value])), selected: null, hover: null };
    const nodes = model.nodes.map(d => {
      const seed = d.seed ?? seedOf(d.id);
      const r = rng(seed);
      const radius = 0.32 + 0.11 * Math.log1p(d.size || 0);
      const inKind = {};                                   // sorte de groupe → [ids], dans l'ordre du nœud
      for (const gid of d.groups || []) {
        const g = groupById.get(String(gid)); if (!g) continue;
        (inKind[g.kind] = inKind[g.kind] || []).push(String(gid));
      }
      const hier = {};                                     // sorte hiérarchique → le groupe ET ses ancêtres
      for (const [k, ids] of Object.entries(inKind)) if ((kinds[k] || {}).hierarchical) hier[k] = new Set(ids.flatMap(chain));
      const n = { d, id: String(d.id), seed, radius, inKind, hier,
                  pos: new THREE.Vector3((r() - .5) * 18 * L.spread, (r() - .5) * 10 * L.spread, (r() - .5) * 18 * L.spread), vel: new THREE.Vector3(),
                  group: new THREE.Group(), visible: true };
      const coreMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 1 });
      n.core = new THREE.Mesh(new THREE.SphereGeometry(radius, 32, 16), coreMat);
      n.core.userData.node = n;
      n.halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true }));
      n.halo.scale.setScalar(radius * 7.5);
      n.shell = new THREE.Mesh(d.shape === 'octa' ? new THREE.OctahedronGeometry(radius * 1.7, 0) : new THREE.IcosahedronGeometry(radius * 1.55, 1),
        new THREE.MeshBasicMaterial({ wireframe: true, transparent: true, opacity: 0.22, depthWrite: false }));
      n.group.add(n.halo, n.core, n.shell);
      // Anneau : un point par appartenance déclarée (un métier…), à sa place dans son catalogue.
      n.ring = new THREE.Group();
      (d.ring || []).forEach(p => {
        const a = (p.slot / Math.max(1, p.of)) * Math.PI * 2;
        const dot = new THREE.Mesh(new THREE.SphereGeometry(0.055, 10, 6), new THREE.MeshBasicMaterial({ color: color(p.color) }));
        dot.position.set(Math.cos(a) * radius * 2.0, 0, Math.sin(a) * radius * 2.0);
        n.ring.add(dot);
      });
      n.ring.rotation.x = 0.35;
      n.group.add(n.ring);
      // Satellites : ce que le nœud porte (un par élément, plafonné côté serveur).
      n.sats = new THREE.Group();
      const items = d.sats || [];
      items.forEach((it, i) => {
        const m = new THREE.Mesh((SAT_SHAPES[it.shape] || SAT_SHAPES.dodeca)(), new THREE.MeshBasicMaterial({ color: color(it.color), transparent: true, opacity: it.opacity ?? 1 }));
        const a = (i / items.length) * Math.PI * 2, rr = radius * 2.9 + (i % 2) * 0.25;
        m.position.set(Math.cos(a) * rr, Math.sin(a * 2) * 0.15, Math.sin(a) * rr);
        n.sats.add(m);
      });
      n.sats.rotation.set(-0.5 + r(), 0, -0.4 + r() * 0.8);
      n.satSpeed = 0.00018 + r() * 0.00018;
      n.group.add(n.sats);
      scene.add(n.group);
      n.label = label('');
      n.label.addEventListener('click', () => select(n));
      n.label.addEventListener('pointerenter', ev => { state.hover = n; showTip(ev, tipHtml(n)); });
      n.label.addEventListener('pointerleave', ev => { state.hover = null; showTip(ev, null); });
      return n;
    });
    const nodeOf = new Map(nodes.map(n => [n.id, n]));
    // Le nom d'un nœud tel qu'on le MONTRE : en clair, ou ses initiales quand les noms sont masqués.
    const masked = () => !!namesLayer && !state.layers[namesLayer];
    const shownName = n => masked() ? initials(n.d.name) : n.d.name;
    function renderNames() {
      for (const n of nodes) n.label.innerHTML = `${esc(shownName(n))}<small>${esc(n.d.sub)}</small>`;
    }

    function paintNodes() {
      const p = palettes[state.colorBy] || { pal: {}, fallback: 0x64748b };
      for (const n of nodes) {
        const cat = (n.d.cats || {})[state.colorBy];
        const c = p.pal[cat] ?? p.fallback;
        n.color = c;
        n.core.material.color.setHex(c).lerp(new THREE.Color(0xffffff), 0.35);
        n.halo.material.color.setHex(c);
        n.shell.material.color.setHex(c);
        if (n.d.faded) { n.core.material.color.multiplyScalar(0.45); n.halo.material.color.multiplyScalar(0.35); }
        n.label.style.color = n.d.faded ? 'var(--wc-ink-mute)' : '';
      }
    }

    // ── Sphères : les groupes déclarés ───────────────────────────────────
    const spheres = [];
    function makeSphere(g, members, also = []) {
      const kd = kinds[g.kind] || {}, col = color(g.color);
      const grp = new THREE.Group();
      const mat = glassMaterial(col, kd.base ?? 0.03, kd.rim ?? 0.55);
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(1, 48, 24), mat);
      const ring = new THREE.Mesh(new THREE.TorusGeometry(1, 0.004, 6, 128),
        new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.45, depthWrite: false }));
      ring.rotation.x = Math.PI / 2;
      grp.add(mesh, ring);
      if (kd.wire) {
        grp.add(new THREE.Mesh(new THREE.IcosahedronGeometry(1.0, 2), new THREE.MeshBasicMaterial({ color: col, wireframe: true, transparent: true, opacity: 0.07, depthWrite: false })));
      }
      scene.add(grp);
      const sub = (g.sub || '') + (also.length ? ` · aussi ${also.slice(0, 3).map(x => x.name).join(', ')}${also.length > 3 ? '…' : ''}` : '');
      const s = { kind: g.kind, kd, obj: g, also, color: col, members, group: grp, mat, ring, center: new THREE.Vector3(), radius: 1,
                  el: label(`${esc(g.name)}<small>${esc(sub)}</small>`, 'sphere'),
                  depth: kd.hierarchical ? depth(g.id) : maxDepth + 1 };
      spheres.push(s);
      return s;
    }
    // Les sortes, dans l'ordre déclaré. Une sorte qui FOND ses groupes (`merge`) : des groupes aux
    // MÊMES membres (deux arbres d'annuaire pour un même labo…) dessineraient des coquilles
    // empilées qui ne disent rien de plus — une seule sphère, celle du groupe le plus fin et le
    // mieux nommé (`weak` : un nœud générique d'annuaire) ; les autres deviennent sa légende.
    for (const [kind, kd] of Object.entries(kinds)) {
      const ofKind = model.groups.filter(g => g.kind === kind);
      const membersOf = g => g.members ? g.members.map(id => nodeOf.get(String(id))).filter(Boolean)
        : nodes.filter(n => kd.hierarchical ? (n.hier[kind] || new Set()).has(String(g.id)) : (n.inKind[kind] || []).includes(String(g.id)));
      if (!kd.merge) {
        for (const g of ofKind) { const members = membersOf(g); if (members.length) makeSphere(g, members); }
        continue;
      }
      const merged = new Map();
      for (const g of ofKind) {
        const members = membersOf(g);
        if (!members.length) continue;
        const key = members.map(n => n.id).sort((a, b) => (Number(a) - Number(b)) || (a < b ? -1 : a > b ? 1 : 0)).join(',');
        if (!merged.has(key)) merged.set(key, { members, gs: [] });
        merged.get(key).gs.push(g);
      }
      for (const { members, gs } of merged.values()) {
        gs.sort((a, b) => ((!!a.weak) - (!!b.weak)) || (depth(b.id) - depth(a.id)));
        const [finest, ...others] = gs;
        makeSphere(finest, members, others);
      }
    }
    const sphereOf = gid => gid == null ? null : spheres.find(s => [s.obj, ...s.also].some(x => String(x.id) === String(gid)));

    // ── Liens : un arc par paire orientée, des particules dans le sens du lien ──
    const links = (model.links || []).map(s => {
      const a = nodeOf.get(String(s.from)), b = nodeOf.get(String(s.to));
      if (!a || !b) return null;
      const col = s.color != null ? color(s.color) : SHARE_COLOR;
      const SEG = 32;
      const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array((SEG + 1) * 3), 3));
      const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: col, transparent: true, opacity: 0.55, depthWrite: false }));
      const NP = Math.min(28, 6 + Math.round(4 * Math.log1p(s.count)));
      const pg = new THREE.BufferGeometry(); pg.setAttribute('position', new THREE.BufferAttribute(new Float32Array(NP * 3), 3));
      const pts = new THREE.Points(pg, new THREE.PointsMaterial({ color: col, size: 0.16, map: GLOW, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
      scene.add(line, pts);
      return { s, a, b, SEG, geo, line, pts, pg, NP, curve: new THREE.QuadraticBezierCurve3(new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()) };
    }).filter(Boolean);

    // Faisceaux : d'un nœud vers un groupe (sa sphère), ou vers le cœur (tout le monde).
    const beams = [];
    for (const bd of model.beams || []) {
      const n = nodeOf.get(String(bd.from)); if (!n) continue;
      const target = sphereOf(bd.to);
      const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
      const line = new THREE.Line(geo, new THREE.LineDashedMaterial({ color: target ? target.color : CORE_COLOR, dashSize: 0.25, gapSize: 0.18, transparent: true, opacity: 0.45 }));
      scene.add(line);
      beams.push({ n, bd, target, geo, line });
    }
    // Co-appartenance (`mesh`) : filets fins entre les membres d'un même groupe.
    const meshLinks = [];
    for (const s of spheres) if (s.kd.mesh) {
      for (let i = 0; i < s.members.length; i++) for (let j = i + 1; j < s.members.length; j++) {
        const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
        const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: s.color, transparent: true, opacity: 0.18, depthWrite: false }));
        scene.add(line); meshLinks.push({ a: s.members[i], b: s.members[j], geo, line, sphere: s });
      }
    }

    // ── Affinité : ce qui rapproche deux nœuds, facteur par facteur ──────
    // Quatre familles (WAMA_SCENES_3D §2) : relationnel (`relation`), catégoriel (`groups`,
    // `hierarchy`, `jaccard`, `same`), numérique (`closeness`) ; le sémantique viendra des voisins.
    function affinity(a, b) {
      const w = state.weights, parts = {}, why = [];
      for (const f of factors) {
        if (f.kind === 'relation') {
          const sh = pairCount.get(pairKey(a.id, b.id)) || 0;
          if (sh) { parts[f.key] = w[f.key] * Math.log2(1 + sh); why.push(`${sh} ${plural(sh, f.one, f.many)}`); }
        } else if (f.kind === 'groups') {
          const pa = a.inKind[f.group] || [];
          const common = (b.inKind[f.group] || []).filter(id => pa.includes(id));
          if (common.length) { parts[f.key] = w[f.key] * common.length; why.push(common.map(id => groupById.get(id).name).join(', ')); }
        } else if (f.kind === 'hierarchy') {
          let best = null;
          const ha = a.hier[f.group] || new Set(), hb = b.hier[f.group] || new Set();
          for (const id of ha) if (hb.has(id) && (best === null || depth(id) > depth(best))) best = id;
          if (best !== null) { parts[f.key] = w[f.key] * (depth(best) + 1) / (maxDepth + 1); why.push(groupById.get(best).name); }
        } else if (f.kind === 'jaccard') {
          const ra = new Set((a.d.sets || {})[f.set] || []), rb = new Set((b.d.sets || {})[f.set] || []);
          const inter = [...ra].filter(k => rb.has(k)).length, uni = new Set([...ra, ...rb]).size;
          if (inter) { parts[f.key] = w[f.key] * inter / uni; why.push(`${inter} ${plural(inter, f.one, f.many)}`); }
        } else if (f.kind === 'same') {
          const va = (a.d.attrs || {})[f.attr], vb = (b.d.attrs || {})[f.attr];
          if (va != null && va !== '' && va === vb) { parts[f.key] = w[f.key]; why.push((f.why || '{v}').replace('{v}', ((a.d.attr_labels || {})[f.attr]) ?? va)); }
        } else if (f.kind === 'closeness') {
          const va = (a.d.attrs || {})[f.attr], vb = (b.d.attrs || {})[f.attr];
          if (va != null && vb != null) {
            const c = 1 - Math.abs(va - vb) / Math.max(1e-9, f.range || 1);
            if (c > 0) { parts[f.key] = w[f.key] * c; why.push(f.why || f.label); }
          }
        }
      }
      return { total: Object.values(parts).reduce((s, v) => s + v, 0), parts, why };
    }
    let pairs = [];
    function rebuildPairs() {
      const vis = nodes.filter(n => n.visible);
      pairs = [];
      for (let i = 0; i < vis.length; i++) for (let j = i + 1; j < vis.length; j++) {
        const af = affinity(vis[i], vis[j]);
        pairs.push({ a: vis[i], b: vis[j], af });
      }
    }
    const nearest = (n, k = 6) => pairs.filter(p => p.a === n || p.b === n).map(p => ({ o: p.a === n ? p.b : p.a, af: p.af }))
      .filter(x => x.af.total > 0).sort((a, b) => b.af.total - a.af.total).slice(0, k);

    // ── Simulation de forces ─────────────────────────────────────────────
    let alpha = 1;
    const tmp = new THREE.Vector3(), cen = new THREE.Vector3();
    function step() {
      const vis = nodes.filter(n => n.visible);
      for (const n of vis) n.force = new THREE.Vector3();
      for (const p of pairs) {
        tmp.subVectors(p.b.pos, p.a.pos); const d = Math.max(0.3, tmp.length()); tmp.divideScalar(d);
        const minGap = p.a.radius + p.b.radius + L.gap;
        let f = -L.repulsion / (d * d) - (d < minGap ? (minGap - d) * L.push : 0);       // répulsion
        if (p.af.total > 0) f += L.spring * Math.min(p.af.total, L.springCap) * (d - L.rest / (1 + p.af.total));   // ressort
        p.a.force.addScaledVector(tmp, f); p.b.force.addScaledVector(tmp, -f);
      }
      // Chaque sphère attire ses membres vers son centre ; un groupe fin tire plus fort (`by_depth`).
      for (const s of spheres) {
        const pull = s.kd.pull;
        const ms = s.members.filter(n => n.visible);
        if (ms.length < 2 || !pull) continue;
        cen.set(0, 0, 0); ms.forEach(n => cen.add(n.pos)); cen.divideScalar(ms.length);
        const k = pull.by_depth ? pull.k * state.weights[pull.weight] * (s.depth + 1) / (maxDepth + 1) : pull.k * state.weights[pull.weight];
        for (const n of ms) n.force.addScaledVector(tmp.subVectors(cen, n.pos), k);
      }
      for (const n of vis) {
        n.force.addScaledVector(n.pos, -L.gravity);                             // gravité douce
        const dc = n.pos.length(), keep = L.coreKeep + n.radius;                // le cœur garde sa place
        if (dc < keep) n.force.addScaledVector(n.pos, (keep - dc) * L.coreKick / Math.max(dc, 0.1));
        n.vel.add(n.force.multiplyScalar(alpha)).multiplyScalar(L.damping);
        if (n.vel.length() > L.maxSpeed) n.vel.setLength(L.maxSpeed);
        n.pos.add(n.vel);
      }
      alpha = Math.max(0, alpha * L.cooling);
    }
    function reheat(a = 0.8) { rebuildPairs(); alpha = Math.max(alpha, a); }

    // ── Mise à jour visuelle ─────────────────────────────────────────────
    const pt = new THREE.Vector3(), mid = new THREE.Vector3();
    const layerOn = key => !key || state.layers[key];
    function updateGeometry(t) {
      for (const n of nodes) {
        n.group.visible = n.visible;
        n.group.position.copy(n.pos);
        n.shell.rotation.y = t * 0.0003 + n.seed; n.shell.rotation.x = t * 0.00017;
        n.ring.rotation.y = -t * 0.0004;
        n.sats.rotation.y = t * n.satSpeed;
        n.sats.visible = layerOn(satsLayer);
        n.halo.material.opacity = 0.75 + 0.15 * Math.sin(t / 700 + n.seed);
      }
      for (const s of spheres) {
        const ms = s.members.filter(n => n.visible);
        const on = ms.length > 0 && layerOn(s.kd.layer);
        s.group.visible = on; s.on = on;
        if (!on) continue;
        cen.set(0, 0, 0); ms.forEach(n => cen.add(n.pos)); cen.divideScalar(ms.length);
        let r = 0; for (const n of ms) r = Math.max(r, cen.distanceTo(n.pos) + n.radius);
        // Un groupe plus large garde une marge plus large : les sphères emboîtées restent lisibles.
        const m = s.kd.margin;
        r += typeof m === 'number' ? m : (m ? m.base + m.per_level * (maxDepth - s.depth) : 1.6);
        s.center.lerp(cen, 0.12); s.radius += (r - s.radius) * 0.12;
        s.group.position.copy(s.center); s.group.scale.setScalar(s.radius);
        s.ring.rotation.z = t * 0.00008 * (s.depth % 2 ? 1 : -1);
      }
      for (const l of links) {
        const on = layerOn(linksLayer) && l.a.visible && l.b.visible;
        l.line.visible = l.pts.visible = on; if (!on) continue;
        const d = l.a.pos.distanceTo(l.b.pos);
        mid.addVectors(l.a.pos, l.b.pos).multiplyScalar(0.5).add(new THREE.Vector3(0, 0.25 * d + 0.5, 0));
        l.curve.v0.copy(l.a.pos); l.curve.v1.copy(mid); l.curve.v2.copy(l.b.pos);
        const arr = l.geo.attributes.position.array;
        for (let i = 0; i <= l.SEG; i++) { l.curve.getPoint(i / l.SEG, pt); arr.set([pt.x, pt.y, pt.z], i * 3); }
        l.geo.attributes.position.needsUpdate = true; l.geo.computeBoundingSphere();
        const parr = l.pg.attributes.position.array;
        for (let i = 0; i < l.NP; i++) { l.curve.getPoint(((t / 3600) + i / l.NP) % 1, pt); parr.set([pt.x, pt.y, pt.z], i * 3); }
        l.pg.attributes.position.needsUpdate = true; l.pg.computeBoundingSphere();
      }
      for (const b of beams) {
        const on = layerOn(linksLayer) && b.n.visible && (!b.target || b.target.on);
        b.line.visible = on; if (!on) continue;
        const to = b.target ? b.target.center : core.position;
        b.geo.attributes.position.array.set([b.n.pos.x, b.n.pos.y, b.n.pos.z, to.x, to.y, to.z]);
        b.geo.attributes.position.needsUpdate = true; b.line.computeLineDistances();
      }
      for (const pl of meshLinks) {
        const on = layerOn(pl.sphere.kd.layer) && pl.a.visible && pl.b.visible;
        pl.line.visible = on; if (!on) continue;
        pl.geo.attributes.position.array.set([pl.a.pos.x, pl.a.pos.y, pl.a.pos.z, pl.b.pos.x, pl.b.pos.y, pl.b.pos.z]);
        pl.geo.attributes.position.needsUpdate = true; pl.geo.computeBoundingSphere();
      }
      coreMesh.rotation.y = t * 0.0005; coreMesh.rotation.x = t * 0.0002;
    }

    // ── Focus : le nœud choisi et ses liens ressortent, le reste s'efface ──
    function neighbours(n) {
      const set = new Set([n]);
      for (const p of pairs) if (p.af.total > 0 && (p.a === n || p.b === n)) set.add(p.a === n ? p.b : p.a);
      return set;
    }
    let litSet = null;
    function applyFocus() {
      const sel = state.selected, near = sel ? neighbours(sel) : null;
      litSet = near;
      for (const n of nodes) {
        const lit = !near || near.has(n);
        n.core.material.opacity = lit ? 1 : 0.18;
        n.halo.material.opacity = lit ? 0.85 : 0.12;
        n.shell.material.opacity = n === sel ? 0.6 : lit ? 0.22 : 0.05;
        n.ring.visible = lit;
        n.label.classList.toggle('dim', !lit);
        n.label.classList.toggle('sel', n === sel);
      }
      for (const s of spheres) {
        const lit = !sel || s.members.includes(sel);
        s.mat.uniforms.uFade.value = lit ? 1 : 0.25;
        s.el.classList.toggle('dim', !lit);
      }
      for (const l of links) {
        const lit = !sel || l.a === sel || l.b === sel;
        l.line.material.opacity = lit ? 0.75 : 0.06; l.pts.material.opacity = lit ? 1 : 0.1;
      }
      for (const b of beams) b.line.material.opacity = !sel || b.n === sel ? 0.5 : 0.05;
      for (const pl of meshLinks) pl.line.material.opacity = !sel || pl.a === sel || pl.b === sel ? 0.3 : 0.04;
    }

    // Vol de caméra : la cible glisse vers l'étoile, la caméra se rapproche sans changer d'angle.
    let flight = null;
    function flyTo(target, dist) {
      const from = controls.target.clone(), dir = camera.position.clone().sub(controls.target).normalize();
      const d0 = camera.position.distanceTo(controls.target);
      flight = { t0: performance.now(), from, to: target.clone(), dir, d0, d1: dist };
    }
    function select(n) {
      state.selected = n;
      if (n) { flyTo(n.pos, Math.max(9, n.radius * 22)); controls.autoRotate = false; }
      else { flyTo(new THREE.Vector3(), homeDistance()); controls.autoRotate = !reduceMotion; }
      applyFocus(); renderPanel();
    }

    // ── Étiquettes projetées ─────────────────────────────────────────────
    function label(html, cls = '') {
      const d = document.createElement('div'); d.className = 'wc-label ' + cls; d.innerHTML = html;
      labelsBox.appendChild(d); return d;
    }
    const v = new THREE.Vector3();
    function place(el, worldPos, visible, yOffset = 0) {
      if (!visible) { el.style.display = 'none'; return; }
      v.copy(worldPos); v.y += yOffset; v.project(camera);
      if (v.z > 1 || v.z < -1) { el.style.display = 'none'; return; }
      el.style.display = '';
      const w = host.clientWidth, h = host.clientHeight;
      el.style.transform = `translate(${((v.x + 1) / 2 * w).toFixed(1)}px, ${((1 - v.y) / 2 * h).toFixed(1)}px) translate(-50%, -50%)`;
    }
    // Une scène peuplée (`label_limit`) n'étiquette que ses plus gros nœuds — plus le choisi, ses
    // voisins et le survolé ; sans limite, toutes les étoiles portent leur nom.
    const limit = spec.label_limit || 0;
    [...nodes].sort((a, b) => (b.d.size || 0) - (a.d.size || 0)).forEach((n, i) => { n.labelRank = i; });
    const labelled = n => !limit || n.labelRank < limit || n === state.selected || n === state.hover || (litSet && litSet.has(n));
    function projectLabels() {
      for (const n of nodes) place(n.label, n.pos, n.visible && labelled(n), -(n.radius * 2.4 + 0.35));
      for (const s of spheres) place(s.el, s.center, s.on, s.radius * 1.02);
      place(coreLabel, core.position, true, -1.1);
    }

    // ── Ce que la scène offre à son volet (`hooks`) ───────────────────────
    const api = { state, nodes, nodeOf, spheres, raw, model, spec, color, css, esc, initials, fmtDate,
                  shownName, nearest, masked, groupById, filterRow: (...a) => filterRow(...a) };

    // ── Survol ───────────────────────────────────────────────────────────
    const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
    function pick(ev) {
      const r = renderer.domElement.getBoundingClientRect();
      mouse.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(mouse, camera);
      const hit = ray.intersectObjects(nodes.filter(n => n.visible).map(n => n.core))[0];
      return hit ? hit.object.userData.node : null;
    }
    function showTip(ev, html) {
      if (!html) { tooltip.style.display = 'none'; return; }
      const r = stage.getBoundingClientRect();
      tooltip.innerHTML = html; tooltip.style.display = 'block';
      tooltip.style.left = Math.min(ev.clientX - r.left + 14, r.width - 310) + 'px';
      tooltip.style.top = (ev.clientY - r.top + 14) + 'px';
    }
    function tipHtml(n) {
      if (hooks.tip) return hooks.tip(n, api);
      const d = n.d;
      return `<b>${esc(shownName(n))}</b>${d.handle && !masked() ? ` <span class="mute">${esc(d.handle)}</span>` : ''}` +
        (d.tip || []).map(line => `<br>${esc(line)}`).join('');
    }
    let downAt = null;
    renderer.domElement.addEventListener('pointerdown', ev => { downAt = [ev.clientX, ev.clientY]; });
    renderer.domElement.addEventListener('pointermove', ev => {
      const n = pick(ev); state.hover = n;
      renderer.domElement.style.cursor = n ? 'pointer' : '';
      showTip(ev, n ? tipHtml(n) : null);
    });
    renderer.domElement.addEventListener('pointerleave', ev => showTip(ev, null));
    renderer.domElement.addEventListener('click', ev => {
      if (downAt && Math.hypot(ev.clientX - downAt[0], ev.clientY - downAt[1]) > 5) return;   // c'était une rotation
      select(pick(ev));
    });
    // Échap rend la sélection — par le clavier commun (`WamaKeys`), recherche comprise comme avant.
    window.WamaKeys.register({ owner: 'constellation', scope: 'page', typing: ['Escape'], handle: ev => {
      if (ev.key !== 'Escape' || !state.selected) return false;
      select(null);
      return true;
    } });

    // ── HUD : couches, couleur, forces, recherche ────────────────────────
    stage.querySelectorAll('.wc-layers .wc-chip[data-layer]').forEach(chip => chip.addEventListener('click', () => {
      const k = chip.dataset.layer; state.layers[k] = !state.layers[k]; chip.classList.toggle('on', state.layers[k]);
      const role = (layers.find(l => l.key === k) || {}).role;
      if (role === 'nodes') { applyVisibility(); reheat(0.9); }
      if (role === 'names') { renderNames(); fillSearch(); renderPanel(); }
    }));
    stage.querySelectorAll('.wc-colorby .wc-chip').forEach(chip => chip.addEventListener('click', () => {
      state.colorBy = chip.dataset.color;
      stage.querySelectorAll('.wc-colorby .wc-chip').forEach(c => c.classList.toggle('on', c === chip));
      paintNodes(); renderPanel();
    }));
    // ── Les MAINS : la scène se DÉCLARE cible de l'interface globale des mains (`wama-hands-ui.js`,
    // icône de la barre du haut, 2026-10-22). L'interface porte la caméra, les mains virtuelles et le
    // pointeur ; la scène dit ce que veulent dire les gestes ici : un poing fermé SAISIT la scène
    // comme la souris (la main va à droite, la scène suit), deux poings qui s'écartent rapprochent
    // la caméra, le pincement choisit l'étoile sous le doigt, le survol montre son infobulle.
    const spherical = new THREE.Spherical(), offset = new THREE.Vector3();
    const HAND_GAIN = 4.5;
    function orbitBy(dx, dy) {
      offset.subVectors(camera.position, controls.target); spherical.setFromVector3(offset);
      spherical.theta -= dx * HAND_GAIN;
      spherical.phi = Math.min(Math.PI - 0.05, Math.max(0.05, spherical.phi - dy * HAND_GAIN));
      offset.setFromSpherical(spherical); camera.position.copy(controls.target).add(offset);
    }
    function zoomBy(f) {
      offset.subVectors(camera.position, controls.target);
      offset.setLength(Math.min(controls.maxDistance, Math.max(controls.minDistance, offset.length() * f)));
      camera.position.copy(controls.target).add(offset);
    }
    const handStill = () => { controls.autoRotate = false; flight = null; };
    import('wama/hands-ui').then(m => m.registerHandTarget({
      element: renderer.domElement,
      rotate: (dx, dy) => { handStill(); orbitBy(dx, dy); },
      zoom: f => { handStill(); zoomBy(f); },
      // Un clic de la main n'est pas la fin d'une rotation à la souris (`downAt`).
      click: (clientX, clientY) => { downAt = null; select(pick({ clientX, clientY })); },
      hover: (clientX, clientY) => {
        const n = pick({ clientX, clientY }); state.hover = n;
        showTip({ clientX, clientY }, n ? tipHtml(n) : null);
      },
      release: () => { controls.autoRotate = !reduceMotion && !state.selected; },
    })).catch(err => console.warn('[constellation] mains indisponibles', err));
    const weightsBox = $('.wc-weights');
    const wid = `wc-${spec.key || 'scene'}-w`;
    for (const w of factors) {
      const row = document.createElement('div'); row.className = 'wc-weight'; row.dataset.weight = w.key;
      row.innerHTML = `<label for="${wid}-${w.key}">${esc(w.label)}</label><output>${w.value}</output>` +
        `<input type="range" id="${wid}-${w.key}" min="0" max="${w.max}" step="0.1" value="${w.value}"><small>${esc(w.help)}</small>`;
      weightsBox.appendChild(row);
      row.querySelector('input').addEventListener('input', ev => {
        state.weights[w.key] = parseFloat(ev.target.value);
        row.querySelector('output').textContent = state.weights[w.key].toFixed(1);
        reheat(0.7); renderPanel();
      });
    }
    const search = $('.wc-search input'), list = $('.wc-search datalist');
    function fillSearch() {
      list.innerHTML = nodes.filter(n => n.visible).map(n => (!masked() ? `<option value="${esc(n.d.name)}">${esc(n.d.handle || '')}</option>` : '')).join('');
    }
    function findNode(q) {
      q = q.trim().toLowerCase(); if (!q) return null;
      const vis = nodes.filter(n => n.visible);
      const name = n => String(n.d.name).toLowerCase(), handle = n => String(n.d.handle || '').toLowerCase();
      return vis.find(n => name(n) === q || (handle(n) && handle(n) === q))
        || vis.find(n => name(n).includes(q) || (handle(n) && handle(n).includes(q))) || null;
    }
    search.addEventListener('change', () => { const n = findNode(search.value); if (n) select(n); });
    search.addEventListener('keydown', ev => { if (ev.key === 'Enter') { const n = findNode(search.value); if (n) select(n); } });

    // ── Filtres de la légende (demande de Fabien, 2026-10-21) ─────────────
    // Une ligne de légende d'une coloration se clique pour masquer ou afficher sa catégorie, son
    // « ◎ » ne garde qu'elle ; une ligne de sphère ne garde que les membres de ce groupe. Les étoiles
    // filtrées SORTENT de la scène et la mise en espace se refait sans elles (comme la couche des
    // comptes de test) : les distances se lisent dans la sélection. Le HUD gauche rappelle les filtres.
    const hidden = {};                       // coloration → catégories masquées
    let groupOnly = null;                    // une sphère : ne garder que ses membres
    const catOf = (n, k) => String((n.d.cats || {})[k]);
    const isHidden = (k, cat) => !!hidden[k] && hidden[k].has(String(cat));
    const filteredOut = n => Object.entries(hidden).some(([k, set]) => set.has(catOf(n, k)))
      || (!!groupOnly && !groupOnly.members.includes(n));
    const catLabel = (k, cat) => ((colorings[k] || {}).legend || []).find(([, c]) => String(c) === cat)?.[0] ?? cat;
    function refilter() { applyVisibility(); reheat(0.9); renderPanel(); renderFilters(); }
    function toggleCat(k, cat) {
      const set = hidden[k] = hidden[k] || new Set();
      if (set.has(cat)) set.delete(cat); else set.add(cat);
      refilter();
    }
    function onlyCat(k, cat) {
      hidden[k] = new Set(nodes.map(n => catOf(n, k)).filter(c => c !== cat));
      refilter();
    }
    // Une ligne de légende filtrante — la légende générique et celle d'une scène (`hooks.legend`).
    const filterRow = (k, cat, inner) => `<div class="wc-legend-row${isHidden(k, cat) ? ' off' : ''}" data-filter="${esc(k)}" data-cat="${esc(cat)}" ` +
      `title="Clic : masquer ou afficher · ◎ : ne garder que celle-ci">${inner}<span class="wc-only" data-only="1">◎</span></div>`;
    const filtersBox = $('.wc-filters');
    function renderFilters() {
      if (!filtersBox) return;
      const chips = [];
      for (const [k, set] of Object.entries(hidden)) {
        if (!set.size) continue;
        const all = [...new Set(nodes.map(n => catOf(n, k)))];
        const shown = all.filter(c => !set.has(c)), off = all.filter(c => set.has(c));
        const text = shown.length < off.length ? `Seulement ${shown.map(c => catLabel(k, c)).join(', ') || '—'}`
          : `Sans ${off.map(c => catLabel(k, c)).join(', ')}`;
        chips.push(`<button type="button" class="wc-chip on" data-clear="${esc(k)}" title="Retirer ce filtre">${esc(text)} ×</button>`);
      }
      if (groupOnly) chips.push(`<button type="button" class="wc-chip on" data-clear="@group" title="Retirer ce filtre">Seulement ${esc(groupOnly.obj.name)} ×</button>`);
      filtersBox.hidden = !chips.length;
      filtersBox.innerHTML = chips.length ? chips.join('') + '<button type="button" class="wc-chip" data-clear="@all">Tout montrer</button>' : '';
      filtersBox.querySelectorAll('[data-clear]').forEach(b => b.addEventListener('click', () => {
        const k = b.dataset.clear;
        if (k === '@all') { for (const key of Object.keys(hidden)) delete hidden[key]; groupOnly = null; }
        else if (k === '@group') groupOnly = null;
        else delete hidden[k];
        refilter();
      }));
    }

    function applyVisibility() {
      for (const n of nodes) n.visible = (!n.d.layer || !!state.layers[n.d.layer]) && !filteredOut(n);
      if (state.selected && !state.selected.visible) select(null);
      fillSearch(); renderStats(); applyFocus();
    }
    // Les mesures déclarées (`spec.stats`) : nœuds visibles, sphères d'une sorte, somme des liens.
    function renderStats() {
      const vis = nodes.filter(n => n.visible);
      const count = st => st.count === 'nodes' ? (st.kind ? vis.filter(n => n.d.kind === st.kind).length : vis.length)
        : st.count === 'groups' ? spheres.filter(s => s.kind === st.kind && s.members.some(n => n.visible)).length
        : st.count === 'links' ? links.filter(l => l.a.visible && l.b.visible).reduce((t, l) => t + l.s.count, 0) : 0;
      statsLine.innerHTML = (spec.stats || []).map(st => { const n = count(st); return `<b>${n}</b> ${plural(n, st.one, st.many)}`; }).join(' · ');
    }

    // ── Volet droit ──────────────────────────────────────────────────────
    let panelShown = null;
    function renderPanel() {
      const n = state.selected;
      panel.innerHTML = n ? (hooks.detail ? hooks.detail(n, api) : detailHtml(n)) : (hooks.legend ? hooks.legend(api) : legendHtml());
      panel.classList.toggle('is-legend', !n);
      if (panelShown !== null && panelShown !== (panel.getBoundingClientRect().width > 0)) resize();   // le centre visuel bouge
      panelShown = panel.getBoundingClientRect().width > 0;
      const close = panel.querySelector('.wc-close'); if (close) close.onclick = () => select(null);
      panel.querySelectorAll('[data-goto]').forEach(el => el.addEventListener('click', () => select(nodeOf.get(String(el.dataset.goto)))));
      panel.querySelectorAll('[data-filter]').forEach(el => el.addEventListener('click', ev => {
        if (ev.target.closest('[data-only]')) onlyCat(el.dataset.filter, el.dataset.cat);
        else toggleCat(el.dataset.filter, el.dataset.cat);
      }));
      panel.querySelectorAll('[data-group]').forEach(el => el.addEventListener('click', () => {
        const s = spheres[Number(el.dataset.group)];
        groupOnly = groupOnly === s ? null : s;
        refilter();
      }));
    }
    // Le volet GÉNÉRIQUE : rendu des sections que la source déclare sur le nœud (`node.detail`).
    function sectionHtml(s) {
      const body = s.type === 'kv' ? `<dl class="wc-kv">${(s.rows || []).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>`
        : s.type === 'list' ? ((s.items || []).length ? `<ul>${s.items.map(it => `<li>${it.goto != null ? `<b data-goto="${esc(it.goto)}" style="cursor:pointer">${esc(it.text)}</b>` : esc(it.text)}${it.note ? ` <span class="mute">${esc(it.note)}</span>` : ''}</li>`).join('')}</ul>` : '')
        : s.type === 'chips' ? (s.groups || []).map(g => { const c = css(color(g.color ?? '--wc-ink-soft'));
            return `<div class="wc-world"><div class="wc-world-head"><span style="color:${c}">${esc(g.label)}</span><span>${esc(g.count ?? '')}</span></div>
            <div class="wc-apps">${(g.items || []).map(it => `<span class="wc-app${it.off ? ' no' : ''}" style="--c:${c}">${esc(it.text)}</span>`).join('')}</div></div>`; }).join('')
        : s.type === 'bars' ? (() => { const max = Math.max(1, ...(s.items || []).map(b => b.value));
            return (s.items || []).map(b => `<div class="wc-bar" style="--c:${css(color(b.color ?? '--wc-media'))}"><span>${esc(b.label)}</span><span>${esc(b.text ?? b.value)}</span><i style="width:${Math.max(3, b.value / max * 100)}%"></i></div>`).join(''); })()
        : '';
      const empty = s.empty && !(s.rows || s.items || s.groups || []).length ? `<p class="mute">${esc(s.empty)}</p>` : '';
      return `<h3>${esc(s.title)}</h3>${body}${empty}${s.note ? `<p class="mute">${esc(s.note)}</p>` : ''}`;
    }
    function detailHtml(n) {
      const d = n.d, det = d.detail || {}, c = css(n.color);
      const near = nearest(n);
      // Titre et phrase d'absence : ceux que la scène déclare (`Scene.nearest_*`, défauts compris).
      const nearHtml = `<h3>${esc(spec.nearest_title)}</h3>${near.length ? `<ul class="wc-near">${near.map(x =>
        `<li data-goto="${esc(x.o.id)}"><span>${esc(shownName(x.o))}</span><span>${x.af.total.toFixed(1)}</span><small>${esc(x.af.why.join(' · '))}</small></li>`).join('')}</ul>`
        : `<p class="mute">${esc(spec.nearest_empty)}</p>`}`;
      return `<button type="button" class="wc-close" title="Fermer (Échap)">×</button>
        <div class="wc-id"><div class="wc-avatar" style="--c:${c}">${esc(det.mark || initials(d.name))}</div>
          <div><h2>${esc(shownName(n))}</h2>${d.handle && !masked() ? `<div class="wc-handle">${esc(d.handle)}</div>` : ''}</div></div>
        ${(det.badges || []).length ? `<div class="wc-badges">${det.badges.map(b => b.color ? `<span class="wc-badge tier" style="--c:${css(color(b.color))}">${esc(b.text)}</span>` : `<span class="wc-badge">${esc(b.text)}</span>`).join('')}</div>` : ''}
        ${det.text ? `<p class="mute" style="margin-top:8px">${esc(det.text)}</p>` : ''}
        ${det.url ? `<p style="margin-top:6px"><a class="wc-link" href="${esc(det.url)}">${esc(det.url_label || 'Ouvrir')} →</a></p>` : ''}
        ${(det.sections || []).map(sectionHtml).join('')}${nearHtml}`;
    }
    // La légende GÉNÉRIQUE : les couleurs du mode choisi, les sphères, les liens, les notes déclarées.
    function legendHtml() {
      const lg = spec.legend || {}, c = colorings[state.colorBy] || {}, p = palettes[state.colorBy] || { pal: {} };
      const kindsShown = [...new Set(spheres.map(s => s.kind))];
      return `<h2>${esc(lg.title || 'Lire la constellation')}</h2>${lg.intro ? `<p>${esc(lg.intro)}</p>` : ''}
        <h3>${esc(lg.nodes_title || 'Étoiles')}</h3>
        ${(c.legend || []).map(([l, cat]) => filterRow(state.colorBy, String(cat), `<span class="sw star" style="--c:${css(p.pal[cat] ?? p.fallback ?? 0x64748b)}"></span>${esc(l)}`)).join('')}
        ${lg.nodes_note ? `<p class="mute">${esc(lg.nodes_note)}</p>` : ''}
        ${(lg.sats || []).map(s => `<div class="wc-legend-row"><span class="sw sat" style="--c:${css(color(s.color))}"></span>${esc(s.label)}</div>`).join('')}
        ${kindsShown.length ? `<h3>${esc(lg.groups_title || 'Sphères')}</h3>` + kindsShown.map(k => {
          // Une ligne par couleur ; elle filtre quand une SEULE sphère porte cette couleur.
          const seen = new Map();
          for (const s of spheres) if (s.kind === k) {
            if (!seen.has(s.color)) seen.set(s.color, { l: s.obj.legend || s.obj.name || (kinds[k] || {}).label || k, ss: [] });
            seen.get(s.color).ss.push(s);
          }
          return [...seen].map(([col, { l, ss }]) => ss.length === 1
            ? `<div class="wc-legend-row${groupOnly === ss[0] ? ' only' : ''}" data-group="${spheres.indexOf(ss[0])}" title="Clic : ne garder que ses membres"><span class="sw" style="--c:${css(col)}"></span>${esc(l)}</div>`
            : `<div class="wc-legend-row"><span class="sw" style="--c:${css(col)}"></span>${esc(l)}</div>`).join(''); }).join('') : ''}
        ${lg.groups_note ? `<p class="mute">${esc(lg.groups_note)}</p>` : ''}
        ${(lg.links || []).length ? `<h3>${esc(lg.links_title || 'Liens')}</h3>` + lg.links.map(l => `<div class="wc-legend-row"><span class="sw line" style="--c:${css(color(l.color))}"></span>${esc(l.label)}</div>`).join('') : ''}
        ${(lg.notes || []).map(t => `<p class="mute">${esc(t)}</p>`).join('')}`;
    }

    // ── Démarrage ────────────────────────────────────────────────────────
    renderNames();
    paintNodes();
    applyVisibility();
    rebuildPairs();
    for (let i = 0; i < L.warmup; i++) step();           // la constellation s'ouvre déjà formée
    alpha = L.idleAlpha;
    renderPanel();

    // Recul de la vue d'ensemble : un écran en portrait voit moins large, la caméra recule d'autant.
    function homeDistance() {
      const aspect = host.clientWidth / Math.max(1, host.clientHeight);
      return L.home * Math.pow(Math.max(1, 1.25 / aspect), 0.8);
    }
    // Le centre VISUEL est entre les deux volets du HUD, pas au milieu de la toile : la vue est
    // décalée d'autant (`setViewOffset`), la projection des étiquettes et le survol le suivent.
    function hudShift(w) {
      const left = $('.wc-hud-left'), right = panel;
      if (w < 761 || !left || !right) return 0;
      const shown = el => el.getBoundingClientRect().width > 0;     // un volet masqué ne prend pas de place
      const l = shown(left) ? left.getBoundingClientRect().right - stage.getBoundingClientRect().left : 0;
      const r = shown(right) ? stage.getBoundingClientRect().right - right.getBoundingClientRect().left : 0;
      return Math.round((r - l) / 2);
    }
    function resize() {
      fitStage();
      const w = host.clientWidth, h = host.clientHeight;
      renderer.setSize(w, h, false);
      camera.aspect = w / Math.max(1, h);
      const shift = hudShift(w);
      if (shift) camera.setViewOffset(w, h, shift, 0, w, h); else camera.clearViewOffset();
      camera.updateProjectionMatrix();
    }
    window.addEventListener('resize', resize);
    // Le volet gauche qui se replie change la largeur de la scène sans redimensionner la fenêtre.
    if (window.ResizeObserver) new ResizeObserver(resize).observe(host);
    resize();
    camera.position.setLength(homeDistance());

    const loop = t => {
      if (alpha > 0.002) step();
      if (flight) {
        const k = Math.min(1, (performance.now() - flight.t0) / 900), e = 1 - Math.pow(1 - k, 3);
        controls.target.lerpVectors(flight.from, state.selected ? state.selected.pos : flight.to, e);
        camera.position.copy(controls.target).addScaledVector(flight.dir, flight.d0 + (flight.d1 - flight.d0) * e);
        if (k >= 1) flight = null;
      } else if (state.selected) {
        // La cible suit l'étoile choisie tant que la constellation bouge encore.
        const delta = state.selected.pos.clone().sub(controls.target);
        controls.target.add(delta); camera.position.add(delta);
      }
      updateGeometry(t);
      controls.update();
      renderer.render(scene, camera);
      projectLabels();
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }
}

// Montage SANS adaptateur : une scène dont la source rend déjà le contrat (licences, modèles…).
export function mountAll() {
  document.querySelectorAll('.wc-stage[data-generic]').forEach(stage => mountConstellation(stage));
}
