/* ==========================================================================
   WAMA — constellation des utilisateurs (2026-10-20, demande de Fabien).

   Chaque personne est une étoile ; la DISTANCE entre deux étoiles se calcule de
   ce qui les lie, avec des poids réglables :
     - un partage (dans un sens ou dans l'autre) rapproche ;
     - un projet commun rapproche ;
     - une unité commune rapproche, d'autant plus qu'elle est fine (équipe > labo > établissement) ;
     - des métiers communs rapprochent un peu.
   Des sphères translucides enveloppent les membres d'une même unité (arbre LDAP/SUPANN) ou d'un
   même projet. Les satellites d'une étoile sont ce qu'elle a fait entrer dans WAMA.

   Les FAITS viennent de `accounts:user-constellation-data` (`accounts/constellation.py`) ; seule la
   mise en espace est calculée ici. Moteur : three.js vendorisé (importmap commune, aucun CDN),
   langage visuel de la scène des mondes (`presentation/wama-presentation-3d.js`).
   ========================================================================== */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const stage = document.getElementById('uc-stage');
const host = document.getElementById('uc-canvas');
const labelsBox = document.getElementById('uc-labels');
const tooltip = document.getElementById('uc-tooltip');
const panel = document.getElementById('uc-panel');
const statsLine = document.getElementById('uc-stats');
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// ── Palette ───────────────────────────────────────────────────────────────
// Profils et mondes : les JETONS de thème (`user-constellation.css`, `--uc-tier-*` / `--uc-world-*`,
// tirés de `--wama-pres-*`), lus à l'ouverture — jamais un hexadécimal recopié ici.
function token(name, fallback = 0x64748b) {
  const v = getComputedStyle(stage).getPropertyValue(name).trim();
  try { return v ? new THREE.Color(v).getHex() : fallback; } catch (e) { return fallback; }
}
let TIER_COLORS = {}, WORLD_COLORS = {}, UNIT_COLORS = {};
let PROJECT_COLOR, SHARE_COLOR, CORE_COLOR, FOG_COLOR, STARS_COLOR;
// Palettes de DESSIN propres à la scène (aucune donnée ne les porte ailleurs) : un point par rôle
// métier, un satellite par famille du catalogue.
const ROLE_PALETTE = [0x93c5fd, 0xf9a8d4, 0xfcd34d, 0x86efac, 0xc4b5fd, 0xfda4af];
const FAMILY_STYLE = {
  models: { color: 0xc4b5fd, geo: () => new THREE.OctahedronGeometry(0.11) },
  functions: { color: 0xfcd34d, geo: () => new THREE.TetrahedronGeometry(0.12) },
  skills: { color: 0xf9a8d4, geo: () => new THREE.BoxGeometry(0.13, 0.13, 0.13) },
  themes: { color: 0x86efac, geo: () => new THREE.TorusGeometry(0.07, 0.025, 6, 14) },
  sandbox_apps: { color: 0x38e1ff, geo: () => new THREE.IcosahedronGeometry(0.11) },
};
const FAMILY_DEFAULT = { color: 0xe2e8f0, geo: () => new THREE.DodecahedronGeometry(0.1) };
const familyStyle = key => FAMILY_STYLE[key] || FAMILY_DEFAULT;

const WEIGHTS = [
  { key: 'share', label: 'Partages', value: 3, max: 6, help: 'Un élément partagé, dans un sens ou dans l\'autre (log du nombre).' },
  { key: 'project', label: 'Projets communs', value: 2.5, max: 6, help: 'Un point par projet partagé.' },
  { key: 'unit', label: 'Unités communes', value: 2, max: 6, help: 'L\'unité commune la plus fine compte le plus.' },
  { key: 'roles', label: 'Métiers communs', value: 0.6, max: 4, help: 'Part des rôles métier en commun.' },
];

const css = hex => '#' + hex.toString(16).padStart(6, '0');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const initials = name => (String(name).match(/[\p{L}\p{N}]+/gu) || ['?']).slice(0, 2).map(w => w[0].toUpperCase()).join('');
const fmtDate = iso => iso ? new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' }) : '—';

// Hasard DÉTERMINISTE (graine = id du compte) : la constellation garde sa forme d'une visite à l'autre.
function rng(seed) {
  let a = (seed * 2654435761) >>> 0;
  return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
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

// ── Moteur ────────────────────────────────────────────────────────────────
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
} else {
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.setClearColor(0x000000, 0);
  host.appendChild(renderer.domElement);
  fetch(stage.dataset.src, { credentials: 'same-origin' })
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(start)
    .catch(err => { statsLine.textContent = `Constellation indisponible (${err.message}).`; });
}

function start(data) {
  TIER_COLORS = Object.fromEntries(data.tiers.map(t => [t.key, token(`--uc-tier-${t.key}`)]));
  WORLD_COLORS = Object.fromEntries(Object.keys(data.worlds).map(w => [w, token(`--uc-world-${w}`)]));
  UNIT_COLORS = Object.fromEntries([...new Set(data.units.map(u => u.type).concat('autre'))]
    .map(t => [t, token(`--uc-unit-${t}`)]));
  [PROJECT_COLOR, SHARE_COLOR, CORE_COLOR, FOG_COLOR, STARS_COLOR] =
    ['--uc-project', '--uc-share', '--uc-core', '--uc-fog', '--uc-stars'].map(n => token(n));
  const GLOW = glowTexture();
  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(FOG_COLOR, 0.012);
  const camera = new THREE.PerspectiveCamera(48, 1, 0.1, 800);
  camera.position.set(0, 9, 34);
  const controls = new OrbitControls(camera, renderer.domElement);
  Object.assign(controls, { enableDamping: true, dampingFactor: 0.07, minDistance: 4, maxDistance: 140,
                            autoRotate: !reduceMotion, autoRotateSpeed: 0.25 });

  // ── Décor : champ d'étoiles lointaines + cœur « WAMA » au centre ─────
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
  const coreLabel = label('WAMA<small>le système</small>', 'core');

  // ── Index des faits ──────────────────────────────────────────────────
  const unitById = new Map(data.units.map(u => [String(u.id), u]));
  const depthCache = new Map();
  const depth = id => {
    id = String(id);
    if (depthCache.has(id)) return depthCache.get(id);
    let d = 0, n = unitById.get(id), guard = 0;
    while (n && n.parent != null && unitById.has(String(n.parent)) && guard++ < 20) { d++; n = unitById.get(String(n.parent)); }
    depthCache.set(id, d); return d;
  };
  const chain = id => {             // unité → … → racine
    const out = []; let n = unitById.get(String(id)), guard = 0;
    while (n && guard++ < 20) { out.push(String(n.id)); n = n.parent != null ? unitById.get(String(n.parent)) : null; }
    return out;
  };
  const maxDepth = Math.max(0, ...data.units.map(u => depth(u.id)));
  const appById = new Map(data.apps.map(a => [a.id, a]));
  const roleIndex = new Map(data.roles.map((r, i) => [r.key, i]));
  const roleLabel = k => (data.roles.find(r => r.key === k) || {}).label || k;
  const familyLabel = k => (data.families.find(f => f.key === k) || {}).label || k;
  const tierLabel = k => (data.tiers.find(t => t.key === k) || {}).label || k;
  const projectsOf = new Map();     // user id → [ {project, role} ]
  for (const p of data.projects) for (const m of p.members) {
    if (!projectsOf.has(m.user)) projectsOf.set(m.user, []);
    projectsOf.get(m.user).push({ project: p, role: m.role_label });
  }
  const shareOut = new Map(), shareIn = new Map(), shareBetween = new Map();
  const pairKey = (a, b) => a < b ? `${a}:${b}` : `${b}:${a}`;
  for (const s of data.shares) {
    if (!shareOut.has(s.from)) shareOut.set(s.from, []); shareOut.get(s.from).push(s);
    if (!shareIn.has(s.to)) shareIn.set(s.to, []); shareIn.get(s.to).push(s);
    shareBetween.set(pairKey(s.from, s.to), (shareBetween.get(pairKey(s.from, s.to)) || 0) + s.count);
  }
  const userById = new Map(data.users.map(u => [u.id, u]));

  // ── Les étoiles ──────────────────────────────────────────────────────
  // `names` : noms affichés, ou initiales seules — éteint d'office quand la présentation intègre la
  // page (`data-embed`), qui se projette devant d'autres personnes.
  const state = { colorBy: 'tier', layers: { units: true, projects: true, shares: true, satellites: true, tests: false,
                                             names: !stage.dataset.embed },
                  weights: Object.fromEntries(WEIGHTS.map(w => [w.key, w.value])), selected: null, hover: null };
  const nodes = data.users.map(u => {
    const r = rng(u.id);
    const total = u.activity.reduce((s, a) => s + a.total, 0);
    const radius = 0.32 + 0.11 * Math.log1p(total);
    const unitSet = new Set(u.units.flatMap(chain));
    const worlds = {};
    for (const a of u.activity) worlds[a.monde] = (worlds[a.monde] || 0) + a.total;
    const topWorld = Object.entries(worlds).sort((a, b) => b[1] - a[1])[0];
    const n = { u, total, radius, unitSet, topWorld: topWorld ? topWorld[0] : null,
                pos: new THREE.Vector3((r() - .5) * 18, (r() - .5) * 10, (r() - .5) * 18), vel: new THREE.Vector3(),
                group: new THREE.Group(), visible: true };
    const coreMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 1 });
    n.core = new THREE.Mesh(new THREE.SphereGeometry(radius, 32, 16), coreMat);
    n.core.userData.node = n;
    n.halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true }));
    n.halo.scale.setScalar(radius * 7.5);
    n.shell = new THREE.Mesh(new THREE.IcosahedronGeometry(radius * 1.55, 1),
      new THREE.MeshBasicMaterial({ wireframe: true, transparent: true, opacity: 0.22, depthWrite: false }));
    n.group.add(n.halo, n.core, n.shell);
    // Anneau des métiers : un point par rôle tenu, à sa place dans le catalogue des rôles.
    n.roles = new THREE.Group();
    u.roles.forEach(k => {
      const i = roleIndex.get(k) ?? 0, a = (i / Math.max(1, data.roles.length)) * Math.PI * 2;
      const dot = new THREE.Mesh(new THREE.SphereGeometry(0.055, 10, 6), new THREE.MeshBasicMaterial({ color: ROLE_PALETTE[i % ROLE_PALETTE.length] }));
      dot.position.set(Math.cos(a) * radius * 2.0, 0, Math.sin(a) * radius * 2.0);
      n.roles.add(dot);
    });
    n.roles.rotation.x = 0.35;
    n.group.add(n.roles);
    // Satellites : ce que la personne a fait entrer dans WAMA (un par élément, plafonné côté serveur).
    n.sats = new THREE.Group();
    const items = Object.entries(u.contributions).flatMap(([fam, f]) => f.items.map(it => ({ fam, ...it })));
    items.forEach((it, i) => {
      const st = familyStyle(it.fam);
      const m = new THREE.Mesh(st.geo(), new THREE.MeshBasicMaterial({ color: it.status === 'promoted' ? 0xffffff : st.color, transparent: true, opacity: it.status === 'owned' ? 0.55 : 1 }));
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
  const nodeOf = new Map(nodes.map(n => [n.u.id, n]));
  // Le nom d'une personne tel qu'on le MONTRE : en clair, ou ses initiales quand les noms sont masqués.
  const shownName = u => state.layers.names ? u.name : initials(u.name);
  function renderNames() {
    for (const n of nodes) n.label.innerHTML = `${esc(shownName(n.u))}<small>${esc(n.u.org.entity || n.u.tier_label)}</small>`;
  }

  function paintNodes() {
    for (const n of nodes) {
      const c = state.colorBy === 'world' ? (WORLD_COLORS[n.topWorld] ?? 0x64748b) : (TIER_COLORS[n.u.tier] ?? 0x94a3b8);
      n.color = c;
      n.core.material.color.setHex(c).lerp(new THREE.Color(0xffffff), 0.35);
      n.halo.material.color.setHex(c);
      n.shell.material.color.setHex(c);
      if (!n.u.active) { n.core.material.color.multiplyScalar(0.45); n.halo.material.color.multiplyScalar(0.35); }
      n.label.style.color = n.u.active ? '' : 'var(--uc-ink-mute)';
    }
  }

  // ── Sphères : unités (arbre LDAP) et projets ─────────────────────────
  const spheres = [];
  function makeSphere(kind, obj, color, members, also = []) {
    const g = new THREE.Group();
    const mat = glassMaterial(color, kind === 'project' ? 0.02 : 0.03, kind === 'project' ? 0.42 : 0.55);
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(1, 48, 24), mat);
    const ring = new THREE.Mesh(new THREE.TorusGeometry(1, 0.004, 6, 128),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.45, depthWrite: false }));
    ring.rotation.x = Math.PI / 2;
    g.add(mesh, ring);
    if (kind === 'project') {
      g.add(new THREE.Mesh(new THREE.IcosahedronGeometry(1.0, 2), new THREE.MeshBasicMaterial({ color, wireframe: true, transparent: true, opacity: 0.07, depthWrite: false })));
    }
    scene.add(g);
    const sub = kind === 'project' ? 'Projet' : obj.type_label + (obj.source === 'profile' ? ' · profil LDAP' : '')
      + (also.length ? ` · aussi ${also.slice(0, 3).map(x => x.name).join(', ')}${also.length > 3 ? '…' : ''}` : '');
    const s = { kind, obj, also, color, members, group: g, mat, ring, center: new THREE.Vector3(), radius: 1,
                el: label(`${esc(obj.name)}<small>${esc(sub)}</small>`, 'sphere'),
                depth: kind === 'unit' ? depth(obj.id) : maxDepth + 1 };
    spheres.push(s);
    return s;
  }
  // Des unités aux MÊMES membres (deux arbres d'annuaire pour un même labo, un établissement dont
  // tous les comptes sont dans un seul labo) dessineraient des coquilles empilées qui ne disent
  // rien de plus : une seule sphère, celle de l'unité la plus fine ; les autres niveaux deviennent
  // sa légende. Une sphère de plus = des membres en plus, rien d'autre.
  const unitGroups = new Map();
  for (const unit of data.units) {
    const members = nodes.filter(n => n.unitSet.has(String(unit.id)));
    if (!members.length) continue;
    const key = members.map(n => n.u.id).sort((a, b) => a - b).join(',');
    if (!unitGroups.has(key)) unitGroups.set(key, { members, units: [] });
    unitGroups.get(key).units.push(unit);
  }
  for (const { members, units } of unitGroups.values()) {
    // Une unité TYPÉE (labo, équipe…) nomme mieux le groupe qu'un nœud « autre » de l'annuaire.
    units.sort((a, b) => ((a.type === 'autre') - (b.type === 'autre')) || (depth(b.id) - depth(a.id)));
    const [finest, ...others] = units;
    makeSphere('unit', finest, UNIT_COLORS[finest.type] ?? UNIT_COLORS.autre, members, others);
  }
  for (const p of data.projects) {
    const members = p.members.map(m => nodeOf.get(m.user)).filter(Boolean);
    if (members.length) makeSphere('project', p, PROJECT_COLOR, members);
  }

  // ── Liens de partage : un arc par paire orientée, des particules dans le sens du partage ──
  const links = data.shares.map(s => {
    const a = nodeOf.get(s.from), b = nodeOf.get(s.to);
    if (!a || !b) return null;
    const SEG = 32;
    const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array((SEG + 1) * 3), 3));
    const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: SHARE_COLOR, transparent: true, opacity: 0.55, depthWrite: false }));
    const NP = Math.min(28, 6 + Math.round(4 * Math.log1p(s.count)));
    const pg = new THREE.BufferGeometry(); pg.setAttribute('position', new THREE.BufferAttribute(new Float32Array(NP * 3), 3));
    const pts = new THREE.Points(pg, new THREE.PointsMaterial({ color: SHARE_COLOR, size: 0.16, map: GLOW, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
    scene.add(line, pts);
    return { s, a, b, SEG, geo, line, pts, pg, NP, curve: new THREE.QuadraticBezierCurve3(new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()) };
  }).filter(Boolean);

  // Partages À UNE PORTÉE : un faisceau de la personne vers sa sphère (unité, projet) ou vers le
  // cœur (tout le monde).
  const beams = [];
  for (const n of nodes) for (const sc of n.u.scope_shares) {
    const target = sc.unit != null ? spheres.find(s => s.kind === 'unit' && [s.obj, ...s.also].some(x => String(x.id) === String(sc.unit)))
      : sc.project != null ? spheres.find(s => s.kind === 'project' && s.obj.id === sc.project) : null;
    const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
    const line = new THREE.Line(geo, new THREE.LineDashedMaterial({ color: target ? target.color : CORE_COLOR, dashSize: 0.25, gapSize: 0.18, transparent: true, opacity: 0.45 }));
    scene.add(line);
    beams.push({ n, sc, target, geo, line });
  }
  // Co-appartenance à un projet : filets fins entre membres.
  const projectLinks = [];
  for (const s of spheres) if (s.kind === 'project') {
    for (let i = 0; i < s.members.length; i++) for (let j = i + 1; j < s.members.length; j++) {
      const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
      const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: PROJECT_COLOR, transparent: true, opacity: 0.18, depthWrite: false }));
      scene.add(line); projectLinks.push({ a: s.members[i], b: s.members[j], geo, line, sphere: s });
    }
  }

  // ── Affinité : ce qui rapproche deux personnes, facteur par facteur ──
  function affinity(a, b) {
    const w = state.weights, parts = {}, why = [];
    const sh = shareBetween.get(pairKey(a.u.id, b.u.id)) || 0;
    if (sh) { parts.share = w.share * Math.log2(1 + sh); why.push(`${sh} partage${sh > 1 ? 's' : ''}`); }
    const pa = (projectsOf.get(a.u.id) || []).map(x => x.project.id);
    const common = (projectsOf.get(b.u.id) || []).filter(x => pa.includes(x.project.id));
    if (common.length) { parts.project = w.project * common.length; why.push(common.map(x => x.project.name).join(', ')); }
    let best = null;
    for (const id of a.unitSet) if (b.unitSet.has(id) && (best === null || depth(id) > depth(best))) best = id;
    if (best !== null) { parts.unit = w.unit * (depth(best) + 1) / (maxDepth + 1); why.push(unitById.get(best).name); }
    const ra = new Set(a.u.roles), rb = new Set(b.u.roles);
    const inter = [...ra].filter(k => rb.has(k)).length, uni = new Set([...ra, ...rb]).size;
    if (inter) { parts.roles = w.roles * inter / uni; why.push(`${inter} métier${inter > 1 ? 's' : ''}`); }
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

  // ── Simulation de forces ─────────────────────────────────────────────
  let alpha = 1;
  const tmp = new THREE.Vector3(), cen = new THREE.Vector3();
  function step() {
    const vis = nodes.filter(n => n.visible);
    for (const n of vis) n.force = new THREE.Vector3();
    for (const p of pairs) {
      tmp.subVectors(p.b.pos, p.a.pos); const d = Math.max(0.3, tmp.length()); tmp.divideScalar(d);
      const minGap = p.a.radius + p.b.radius + 1.2;
      let f = -26 / (d * d) - (d < minGap ? (minGap - d) * 0.6 : 0);       // répulsion
      if (p.af.total > 0) f += 0.045 * Math.min(p.af.total, 8) * (d - 13 / (1 + p.af.total));   // ressort
      p.a.force.addScaledVector(tmp, f); p.b.force.addScaledVector(tmp, -f);
    }
    // Chaque sphère attire ses membres vers son centre ; les unités fines tirent plus fort.
    for (const s of spheres) {
      const ms = s.members.filter(n => n.visible);
      if (ms.length < 2) continue;
      cen.set(0, 0, 0); ms.forEach(n => cen.add(n.pos)); cen.divideScalar(ms.length);
      const k = s.kind === 'project' ? 0.012 * state.weights.project : 0.008 * state.weights.unit * (s.depth + 1) / (maxDepth + 1);
      for (const n of ms) n.force.addScaledVector(tmp.subVectors(cen, n.pos), k);
    }
    for (const n of vis) {
      n.force.addScaledVector(n.pos, -0.012);                                 // gravité douce
      const dc = n.pos.length(), keep = 3.8 + n.radius;                       // le cœur garde sa place
      if (dc < keep) n.force.addScaledVector(n.pos, (keep - dc) * 0.4 / Math.max(dc, 0.1));
      n.vel.add(n.force.multiplyScalar(alpha)).multiplyScalar(0.82);
      if (n.vel.length() > 1.2) n.vel.setLength(1.2);
      n.pos.add(n.vel);
    }
    alpha = Math.max(0, alpha * 0.993);
  }
  function reheat(a = 0.8) { rebuildPairs(); alpha = Math.max(alpha, a); }

  // ── Mise à jour visuelle ─────────────────────────────────────────────
  const pt = new THREE.Vector3(), mid = new THREE.Vector3();
  function updateGeometry(t) {
    for (const n of nodes) {
      n.group.visible = n.visible;
      n.group.position.copy(n.pos);
      n.shell.rotation.y = t * 0.0003 + n.u.id; n.shell.rotation.x = t * 0.00017;
      n.roles.rotation.y = -t * 0.0004;
      n.sats.rotation.y = t * n.satSpeed;
      n.sats.visible = state.layers.satellites;
      n.halo.material.opacity = 0.75 + 0.15 * Math.sin(t / 700 + n.u.id);
    }
    for (const s of spheres) {
      const ms = s.members.filter(n => n.visible);
      const on = ms.length > 0 && state.layers[s.kind === 'project' ? 'projects' : 'units'];
      s.group.visible = on; s.on = on;
      if (!on) continue;
      cen.set(0, 0, 0); ms.forEach(n => cen.add(n.pos)); cen.divideScalar(ms.length);
      let r = 0; for (const n of ms) r = Math.max(r, cen.distanceTo(n.pos) + n.radius);
      // Une unité plus large garde une marge plus large : les sphères emboîtées restent lisibles.
      r += s.kind === 'project' ? 1.6 : 1.1 + 0.9 * (maxDepth - s.depth);
      s.center.lerp(cen, 0.12); s.radius += (r - s.radius) * 0.12;
      s.group.position.copy(s.center); s.group.scale.setScalar(s.radius);
      s.ring.rotation.z = t * 0.00008 * (s.depth % 2 ? 1 : -1);
    }
    for (const l of links) {
      const on = state.layers.shares && l.a.visible && l.b.visible;
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
      const on = state.layers.shares && b.n.visible && (!b.target || b.target.on);
      b.line.visible = on; if (!on) continue;
      const to = b.target ? b.target.center : core.position;
      b.geo.attributes.position.array.set([b.n.pos.x, b.n.pos.y, b.n.pos.z, to.x, to.y, to.z]);
      b.geo.attributes.position.needsUpdate = true; b.line.computeLineDistances();
    }
    for (const pl of projectLinks) {
      const on = state.layers.projects && pl.a.visible && pl.b.visible;
      pl.line.visible = on; if (!on) continue;
      pl.geo.attributes.position.array.set([pl.a.pos.x, pl.a.pos.y, pl.a.pos.z, pl.b.pos.x, pl.b.pos.y, pl.b.pos.z]);
      pl.geo.attributes.position.needsUpdate = true; pl.geo.computeBoundingSphere();
    }
    coreMesh.rotation.y = t * 0.0005; coreMesh.rotation.x = t * 0.0002;
  }

  // ── Focus : la personne choisie et ses liens ressortent, le reste s'efface ──
  function neighbours(n) {
    const set = new Set([n]);
    for (const p of pairs) if (p.af.total > 0 && (p.a === n || p.b === n)) set.add(p.a === n ? p.b : p.a);
    return set;
  }
  function applyFocus() {
    const sel = state.selected, near = sel ? neighbours(sel) : null;
    for (const n of nodes) {
      const lit = !near || near.has(n);
      n.core.material.opacity = lit ? 1 : 0.18;
      n.halo.material.opacity = lit ? 0.85 : 0.12;
      n.shell.material.opacity = n === sel ? 0.6 : lit ? 0.22 : 0.05;
      n.roles.visible = lit;
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
    for (const pl of projectLinks) pl.line.material.opacity = !sel || pl.a === sel || pl.b === sel ? 0.3 : 0.04;
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
    const d = document.createElement('div'); d.className = 'uc-label ' + cls; d.innerHTML = html;
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
  function projectLabels() {
    for (const n of nodes) place(n.label, n.pos, n.visible, -(n.radius * 2.4 + 0.35));
    for (const s of spheres) place(s.el, s.center, s.on, s.radius * 1.02);
    place(coreLabel, core.position, true, -1.1);
  }

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
    const u = n.u;
    return `<b>${esc(shownName(u))}</b>${state.layers.names ? ` <span class="mute">@${esc(u.username)}</span>` : ""}<br>${esc(u.tier_label)}` +
      (u.roles.length ? ' · ' + u.roles.map(k => esc(roleLabel(k))).join(', ') : '') +
      (u.org.entity ? `<br>${esc(u.org.entity)}` : '') +
      `<br><span class="mute">${n.total} élément${n.total > 1 ? 's' : ''} traités · ${u.apps.length}/${data.apps.length} outils</span>`;
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
  document.addEventListener('keydown', ev => { if (ev.key === 'Escape' && state.selected) select(null); });

  // ── HUD : couches, couleur, forces, recherche ────────────────────────
  document.querySelectorAll('#uc-layers .uc-chip').forEach(chip => chip.addEventListener('click', () => {
    const k = chip.dataset.layer; state.layers[k] = !state.layers[k]; chip.classList.toggle('on', state.layers[k]);
    if (k === 'tests') { applyVisibility(); reheat(0.9); }
    if (k === 'names') { renderNames(); fillSearch(); renderPanel(); }
  }));
  document.querySelectorAll('#uc-colorby .uc-chip').forEach(chip => chip.addEventListener('click', () => {
    state.colorBy = chip.dataset.color;
    document.querySelectorAll('#uc-colorby .uc-chip').forEach(c => c.classList.toggle('on', c === chip));
    paintNodes(); renderPanel();
  }));
  const weightsBox = document.getElementById('uc-weights');
  for (const w of WEIGHTS) {
    const row = document.createElement('div'); row.className = 'uc-weight';
    row.innerHTML = `<label for="uc-w-${w.key}">${esc(w.label)}</label><output id="uc-wo-${w.key}">${w.value}</output>` +
      `<input type="range" id="uc-w-${w.key}" min="0" max="${w.max}" step="0.1" value="${w.value}"><small>${esc(w.help)}</small>`;
    weightsBox.appendChild(row);
    row.querySelector('input').addEventListener('input', ev => {
      state.weights[w.key] = parseFloat(ev.target.value);
      row.querySelector('output').textContent = state.weights[w.key].toFixed(1);
      reheat(0.7); renderPanel();
    });
  }
  const search = document.getElementById('uc-search'), list = document.getElementById('uc-search-list');
  function fillSearch() {
    list.innerHTML = nodes.filter(n => n.visible).map(n => (state.layers.names ? `<option value="${esc(n.u.name)}">${esc(n.u.username)}</option>` : "")).join('');
  }
  function findNode(q) {
    q = q.trim().toLowerCase(); if (!q) return null;
    const vis = nodes.filter(n => n.visible);
    return vis.find(n => n.u.name.toLowerCase() === q || n.u.username.toLowerCase() === q)
      || vis.find(n => n.u.name.toLowerCase().includes(q) || n.u.username.toLowerCase().includes(q)) || null;
  }
  search.addEventListener('change', () => { const n = findNode(search.value); if (n) select(n); });
  search.addEventListener('keydown', ev => { if (ev.key === 'Enter') { const n = findNode(search.value); if (n) select(n); } });

  function applyVisibility() {
    for (const n of nodes) n.visible = state.layers.tests || n.u.kind === 'person';
    if (state.selected && !state.selected.visible) select(null);
    fillSearch(); renderStats(); applyFocus();
  }
  function renderStats() {
    const vis = nodes.filter(n => n.visible);
    const ids = new Set(vis.map(n => n.u.id));
    const shares = data.shares.filter(s => ids.has(s.from) && ids.has(s.to)).reduce((t, s) => t + s.count, 0);
    const units = spheres.filter(s => s.kind === 'unit' && s.members.some(n => n.visible)).length;
    const projects = spheres.filter(s => s.kind === 'project' && s.members.some(n => n.visible)).length;
    statsLine.innerHTML = `<b>${vis.length}</b> personne${vis.length > 1 ? 's' : ''} · <b>${units}</b> unité${units > 1 ? 's' : ''} · ` +
      `<b>${projects}</b> projet${projects > 1 ? 's' : ''} · <b>${shares}</b> partage${shares > 1 ? 's' : ''} entre personnes`;
  }

  // ── Volet droit ──────────────────────────────────────────────────────
  let panelShown = null;
  function renderPanel() {
    const n = state.selected;
    panel.innerHTML = n ? personHtml(n) : legendHtml();
    panel.classList.toggle('is-legend', !n);
    if (panelShown !== null && panelShown !== (panel.getBoundingClientRect().width > 0)) resize();   // le centre visuel bouge
    panelShown = panel.getBoundingClientRect().width > 0;
    const close = panel.querySelector('.uc-close'); if (close) close.onclick = () => select(null);
    panel.querySelectorAll('[data-goto]').forEach(el => el.addEventListener('click', () => select(nodeOf.get(Number(el.dataset.goto)))));
  }
  function legendHtml() {
    const types = [...new Set(spheres.filter(s => s.kind === 'unit').map(s => s.obj.type))];
    const uncarried = data.uncarried_families.map(f => esc(f.label)).join(', ');
    return `<h2>Lire la constellation</h2>
      <p>Chaque étoile est une personne. Cliquez-en une pour tout voir d'elle : profil, métiers, droits, projets, partages, contributions et activité.</p>
      <h3>Étoiles</h3>
      ${(state.colorBy === 'tier' ? data.tiers.map(t => [t.label, TIER_COLORS[t.key]]) : Object.entries(data.worlds).map(([k, l]) => [l, WORLD_COLORS[k] ?? 0x64748b]))
        .map(([l, c]) => `<div class="uc-legend-row"><span class="sw star" style="--c:${css(c)}"></span>${esc(l)}</div>`).join('')}
      <p class="mute">Taille = volume traité (journal). Étoile pâle = compte inactif.</p>
      <div class="uc-legend-row"><span class="sw" style="--c:${css(ROLE_PALETTE[0])};width:6px;height:6px;border:0;background:${css(ROLE_PALETTE[0])}"></span>Anneau de points : un par métier tenu</div>
      ${data.families.map(f => `<div class="uc-legend-row"><span class="sw sat" style="--c:${css(familyStyle(f.key).color)}"></span>Satellite : ${esc(f.label)}</div>`).join('')}
      <h3>Sphères</h3>
      ${types.map(tp => `<div class="uc-legend-row"><span class="sw" style="--c:${css(UNIT_COLORS[tp] ?? UNIT_COLORS.autre)}"></span>${esc((data.units.find(u => u.type === tp) || {}).type_label || tp)}</div>`).join('')}
      <div class="uc-legend-row"><span class="sw" style="--c:${css(PROJECT_COLOR)}"></span>Projet</div>
      <p class="mute">Une sphère enveloppe les membres d'une unité de l'annuaire (et de ses sous-unités) ou d'un projet ; les plus larges englobent les plus fines.</p>
      <h3>Liens</h3>
      <div class="uc-legend-row"><span class="sw line" style="--c:${css(SHARE_COLOR)}"></span>Partage à une personne — les particules vont de celui qui partage à celui qui reçoit</div>
      <div class="uc-legend-row"><span class="sw line" style="--c:${css(CORE_COLOR)}"></span>Pointillés : partage à une unité, un projet ou à tous (vers le cœur)</div>
      ${!data.projects.length ? '<p class="mute">Aucun projet n\'est déclaré pour l\'instant.</p>' : ''}
      ${uncarried ? `<h3>Pas encore montré</h3><p class="mute">Ces familles du catalogue ne portent pas encore leur auteur (ROADMAP §29) : ${uncarried}.</p>` : ''}`;
  }
  function personHtml(n) {
    const u = n.u, c = css(n.color);
    const sections = [];
    // Organisation
    const units = u.units.map(id => unitById.get(String(id))).filter(Boolean);
    sections.push(`<h3>Organisation</h3><dl class="uc-kv">
      ${u.org.path ? `<dt>Rattachement</dt><dd>${esc(u.org.path)}</dd>` : ''}
      ${u.org.establishment ? `<dt>Établissement</dt><dd>${esc(u.org.establishment)}</dd>` : ''}
      ${u.org.affiliation ? `<dt>Affiliation</dt><dd>${esc(u.org.affiliation)}</dd>` : ''}
      ${units.length ? `<dt>Unités</dt><dd>${units.map(x => `${esc(x.name)} <span class="mute">${esc(x.type_label)}</span>${x.source === 'profile' ? '<span class="uc-tag" title="Portée par le profil LDAP, absente de l\'arbre des unités synchronisé">profil</span>' : ''}`).join('<br>')}</dd>` : ''}
      </dl>${!u.org.path && !units.length ? '<p class="mute">Aucun rattachement connu (compte local ou annuaire sans entité).</p>' : ''}`);
    // Projets
    const projs = projectsOf.get(u.id) || [];
    sections.push(`<h3>Projets</h3>${projs.length ? `<ul>${projs.map(x => `<li><b>${esc(x.project.name)}</b> <span class="mute">${esc(x.role)}</span></li>`).join('')}</ul>` : '<p class="mute">Aucun projet.</p>'}`);
    // Droits
    const can = new Set(u.apps);
    const byWorld = {};
    for (const a of data.apps) (byWorld[a.world || 'autre'] = byWorld[a.world || 'autre'] || []).push(a);
    sections.push(`<h3>Droits · ${u.apps.length}/${data.apps.length} outils</h3>` + Object.entries(byWorld).map(([w, apps]) => {
      const wc = css(WORLD_COLORS[w] ?? 0x64748b), k = apps.filter(a => can.has(a.id)).length;
      return `<div class="uc-world"><div class="uc-world-head"><span style="color:${wc}">${esc(data.worlds[w] || w)}</span><span>${k}/${apps.length}</span></div>
        <div class="uc-apps">${apps.map(a => `<span class="uc-app${can.has(a.id) ? '' : ' no'}" style="--c:${wc}">${esc(a.label)}</span>`).join('')}</div></div>`;
    }).join('') + (u.active ? '' : '<p class="mute">Compte inactif : aucun outil ouvert.</p>'));
    // Contributions
    const fams = Object.entries(u.contributions);
    const uncarried = data.uncarried_families.map(f => esc(f.label)).join(', ');
    sections.push(`<h3>Apports à WAMA</h3>` + (fams.length ? fams.map(([k, f]) => {
      const tot = f.owned + f.shared + f.promoted;
      const detail = [f.owned && `${f.owned} privé${f.owned > 1 ? 's' : ''}`, f.shared && `${f.shared} partagé${f.shared > 1 ? 's' : ''}`, f.promoted && `${f.promoted} promu${f.promoted > 1 ? 's' : ''} au système`].filter(Boolean).join(' · ');
      return `<div class="uc-family"><div class="uc-family-head"><span class="sw" style="--c:${css(familyStyle(k).color)}"></span>${esc(familyLabel(k))}<span class="n">${tot}</span></div>
        <div class="items">${f.items.map(it => it.status === 'promoted' ? `<em>${esc(it.name)}</em>` : esc(it.name)).join(', ')}${tot > f.items.length ? '…' : ''}<br><span class="mute">${detail}</span></div></div>`;
    }).join('') : '<p class="mute">Rien d\'ajouté au catalogue pour l\'instant.</p>') +
      (uncarried ? `<p class="mute">Non suivi par auteur : ${uncarried}.</p>` : ''));
    // Activité
    const act = u.activity.slice(0, 8), max = Math.max(1, ...act.map(a => a.total));
    sections.push(`<h3>Activité · ${n.total} élément${n.total > 1 ? 's' : ''}</h3>` + (act.length ? act.map(a =>
      `<div class="uc-bar" style="--c:${css(WORLD_COLORS[a.monde] ?? 0x64748b)}"><span>${esc(a.label)}</span><span>${a.total}</span><i style="width:${Math.max(3, a.total / max * 100)}%"></i></div>`).join('') +
      (u.activity.length > act.length ? `<p class="mute">et ${u.activity.length - act.length} autre(s) outil(s).</p>` : '') : '<p class="mute">Aucun élément au journal.</p>'));
    // Partages
    const out = shareOut.get(u.id) || [], inn = shareIn.get(u.id) || [];
    const who = id => { const x = userById.get(id); return x ? `<b data-goto="${id}" style="cursor:pointer">${esc(shownName(x))}</b>` : '?'; };
    const lv = s => Object.entries(s.levels).map(([k, m]) => `${m} × ${esc((data.levels[k] || k).toLowerCase())}`).join(', ');
    // La portée : l'unité ou le projet NOMMÉ quand il y en a un, sinon le libellé déclaré de la portée.
    const scopeName = sc => (sc.unit != null && (unitById.get(String(sc.unit)) || {}).name)
      || (sc.project != null && (data.projects.find(p => p.id === sc.project) || {}).name)
      || data.scopes[sc.visibility] || sc.visibility;
    const shareLines = [
      ...out.map(s => `<li>→ ${who(s.to)} <span class="mute">${lv(s)}</span></li>`),
      ...inn.map(s => `<li>← ${who(s.from)} <span class="mute">${lv(s)}</span></li>`),
      ...u.scope_shares.map(sc => `<li>⇢ ${esc(scopeName(sc))} <span class="mute">${sc.count} élément${sc.count > 1 ? 's' : ''}</span></li>`),
    ];
    sections.push(`<h3>Partages</h3>${shareLines.length ? `<ul>${shareLines.join('')}</ul>` : '<p class="mute">Aucun partage en vigueur.</p>'}`);
    // Proximités
    const near = pairs.filter(p => p.a === n || p.b === n).map(p => ({ o: p.a === n ? p.b : p.a, af: p.af }))
      .filter(x => x.af.total > 0).sort((a, b) => b.af.total - a.af.total).slice(0, 6);
    sections.push(`<h3>Les plus proches</h3>${near.length ? `<ul class="uc-near">${near.map(x =>
      `<li data-goto="${x.o.u.id}"><span>${esc(shownName(x.o.u))}</span><span>${x.af.total.toFixed(1)}</span><small>${esc(x.af.why.join(' · '))}</small></li>`).join('')}</ul>`
      : '<p class="mute">Rien ne relie encore ce compte aux autres : son étoile flotte librement.</p>'}`);

    return `<button type="button" class="uc-close" title="Fermer (Échap)">×</button>
      <div class="uc-id"><div class="uc-avatar" style="--c:${c}">${esc(initials(u.name))}</div>
        <div><h2>${esc(shownName(u))}</h2>${state.layers.names ? `<div class="uc-handle">@${esc(u.username)}</div>` : ""}</div></div>
      <div class="uc-badges">
        <span class="uc-badge tier" style="--c:${css(TIER_COLORS[u.tier] ?? 0x94a3b8)}">${esc(tierLabel(u.tier))}</span>
        ${u.roles.map(k => `<span class="uc-badge"><span class="sw" style="--c:${css(ROLE_PALETTE[(roleIndex.get(k) ?? 0) % ROLE_PALETTE.length])}"></span>${esc(roleLabel(k))}</span>`).join('')}
        ${u.active ? '' : '<span class="uc-badge off">Inactif</span>'}
        ${u.kind !== 'person' ? `<span class="uc-badge">${esc(data.account_kinds[u.kind] || u.kind)}</span>` : ''}
      </div>
      <p class="mute" style="margin-top:8px">Inscrit le ${fmtDate(u.joined)} · dernière connexion ${fmtDate(u.last_login)}</p>
      ${sections.join('')}`;
  }

  // ── Démarrage ────────────────────────────────────────────────────────
  renderNames();
  paintNodes();
  applyVisibility();
  rebuildPairs();
  for (let i = 0; i < 260; i++) step();           // la constellation s'ouvre déjà formée
  alpha = 0.25;
  renderPanel();

  // Recul de la vue d'ensemble : un écran en portrait voit moins large, la caméra recule d'autant.
  function homeDistance() {
    const aspect = host.clientWidth / Math.max(1, host.clientHeight);
    return 36 * Math.pow(Math.max(1, 1.25 / aspect), 0.8);
  }
  // Le centre VISUEL est entre les deux volets du HUD, pas au milieu de la toile : la vue est
  // décalée d'autant (`setViewOffset`), la projection des étiquettes et le survol le suivent.
  function hudShift(w) {
    const left = document.querySelector('.uc-hud-left'), right = panel;
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
